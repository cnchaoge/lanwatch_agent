"""
网络故障检测与记录模块。

结构：
- NetworkMonitor：后台线程，每 10 秒检测一次连通性
- 检测链：本机网卡 → 网关 → DNS(114.114.114.114) → 公网(baidu.com)
- 断线判定：连续 3 次失败
- 恢复判定：连续 2 次成功
- 断线时自动触发 tracert + nslookup 诊断，分析故障点
- 写入 SQLite network_events 表
"""
import sqlite3
import threading
import time
import logging
import subprocess
import platform
import os
import sys
import re

from typing import Optional, Dict, List

log = logging.getLogger("network_monitor")

# ── 数据库 ──────────────────────────────────────────────────────
EVENTS_DB = os.path.join(
    os.environ.get("PROGRAMDATA", "C:\\ProgramData"),
    "LanwatchAgent", "network_events.db"
)

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS network_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    start_time DATETIME NOT NULL,
    end_time DATETIME,
    duration_seconds INTEGER,
    gateway TEXT,
    target TEXT,
    error_message TEXT,
    hop_count INTEGER,
    diag_traceroute TEXT,
    diag_nslookup TEXT,
    diag_conclusion TEXT,
    recovery_diag TEXT,
    root_cause_hint TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
"""

INSERT_SQL = """
INSERT INTO network_events
    (event_type, start_time, end_time, duration_seconds,
     gateway, target, error_message, hop_count)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
"""

UPDATE_END_SQL = """
UPDATE network_events
SET end_time = ?, duration_seconds = ?
WHERE id = ?
"""

UPDATE_DIAG_SQL = """
UPDATE network_events
SET diag_traceroute = ?, diag_nslookup = ?, diag_conclusion = ?
WHERE id = ?
"""

UPDATE_RECOVERY_SQL = """
UPDATE network_events
SET recovery_diag = ?, root_cause_hint = ?
WHERE id = ?
"""


def _migrate_db(conn: sqlite3.Connection):
    """为旧数据库增加诊断相关列（幂等）"""
    for col in ("diag_traceroute", "diag_nslookup", "diag_conclusion",
                "recovery_diag", "root_cause_hint"):
        try:
            conn.execute("ALTER TABLE network_events ADD COLUMN %s TEXT" % col)
        except sqlite3.OperationalError:
            pass  # 列已存在


def get_db() -> sqlite3.Connection:
    """获取数据库连接（每次调用新建，调用方负责 close）"""
    os.makedirs(os.path.dirname(EVENTS_DB), exist_ok=True)
    conn = sqlite3.connect(EVENTS_DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(CREATE_TABLE_SQL)
    _migrate_db(conn)
    return conn


# ── 查询接口 ────────────────────────────────────────────────────

def query_events(limit: int = 50, offset: int = 0) -> List[Dict]:
    """按时间倒序查询故障事件"""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM network_events ORDER BY id DESC LIMIT ? OFFSET ?",
            (limit, offset)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def count_events() -> int:
    """查询事件总数"""
    conn = get_db()
    try:
        row = conn.execute("SELECT COUNT(*) AS cnt FROM network_events").fetchone()
        return row["cnt"] if row else 0
    finally:
        conn.close()


def get_recent_offline() -> Optional[Dict]:
    """获取最近一条未恢复的离线事件（end_time IS NULL）"""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM network_events WHERE event_type='offline' AND end_time IS NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ── ping 工具 ───────────────────────────────────────────────────

def _ping(host: str, timeout: int = 2) -> bool:
    """ping 一次，返回是否可达"""
    is_win = platform.system().lower() == "windows"
    param = "-n" if is_win else "-c"
    timeout_flag = "-w" if is_win else "-W"
    timeout_val = str(timeout * 1000) if is_win else str(timeout)
    try:
        r = subprocess.run(
            ["ping", param, "1", timeout_flag, timeout_val, host],
            capture_output=True, text=True,
            timeout=timeout + 1,
            startupinfo=_hide_window()
        )
        return r.returncode == 0
    except Exception:
        return False


def _hide_window():
    """创建 STARTUPINFO 隐藏窗口"""
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = subprocess.SW_HIDE
    return si


def _get_gateway() -> str:
    """获取默认网关 IP"""
    try:
        if platform.system().lower() == "windows":
            out = subprocess.check_output(
                "route print -4", shell=True,
                stderr=subprocess.DEVNULL, text=True
            )
            for line in out.splitlines():
                line = line.strip()
                parts = line.split()
                if len(parts) >= 3 and parts[0] == "0.0.0.0":
                    return parts[2]
        else:
            out = subprocess.check_output(
                "ip route | grep default", shell=True,
                stderr=subprocess.DEVNULL, text=True
            )
            parts = out.decode().split()
            if "via" in parts:
                return parts[parts.index("via") + 1]
    except Exception:
        pass
    return ""


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


# ── 诊断工具（tracert + nslookup）─────────────────────────────

DIAG_TARGETS = [
    "114.114.114.114",
    "www.baidu.com",
]

DIAG_DOMAIN = "www.baidu.com"


def run_tracert(target: str = "114.114.114.114",
                max_hops: int = 15,
                timeout: int = 20) -> str:
    """执行 tracert，返回完整输出文本"""
    is_win = platform.system().lower() == "windows"
    if is_win:
        # 用 cmd.exe /c 保证找到 System32 下的 tracert（解决 32 位 Python 路径重定向）
        cmd = ["cmd.exe", "/c", "tracert", "-h", str(max_hops), "-w", "2000", target]
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = subprocess.SW_HIDE
    else:
        cmd = ["traceroute", "-m", str(max_hops), "-w", "2", target]
        si = None
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout,
                           encoding="gbk" if is_win else "utf-8",
                           errors="replace", startupinfo=si)
        out = (r.stdout or "") + "\n" + (r.stderr or "")
        log.info("[诊断] tracert %s 返回码=%d, 输出=%d行, stderr=%s",
                 target, r.returncode, len(out.splitlines()), (r.stderr or "")[:100])
        return out.strip()
    except subprocess.TimeoutExpired:
        log.warning("[诊断] tracert %s 超时(%ds)", target, timeout)
        return "[tracert 执行超时]"
    except Exception as e:
        log.warning("[诊断] tracert %s 错误: %s", target, e)
        return "[tracert 错误: %s]" % e


def run_nslookup(domain: str = "www.baidu.com",
                 timeout: int = 10) -> str:
    """执行 nslookup，返回完整输出"""
    cmd = ["nslookup", domain]
    is_win = platform.system().lower() == "windows"
    if is_win:
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = subprocess.SW_HIDE
    else:
        si = None
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout,
                           encoding="gbk" if is_win else "utf-8",
                           errors="replace", startupinfo=si)
        out = (r.stdout or "") + "\n" + (r.stderr or "")
        log.info("[诊断] nslookup %s 返回码=%d, 输出=%d行, stderr=%s",
                 domain, r.returncode, len(out.splitlines()), (r.stderr or "")[:100])
        return out.strip()
    except subprocess.TimeoutExpired:
        log.warning("[诊断] nslookup %s 超时(%ds)", domain, timeout)
        return "[nslookup 执行超时]"
    except Exception as e:
        log.warning("[诊断] nslookup %s 错误: %s", domain, e)
        return "[nslookup 错误: %s]" % e


def _parse_tracert_hops(tracert_out: str) -> List[Dict]:
    """解析 tracert 输出，返回每跳状态列表"""
    hops = []
    for line in tracert_out.splitlines():
        line = line.strip()
        m = re.match(r"^(\d+)\s+", line)
        if not m:
            continue
        hop_num = int(m.group(1))
        tokens = line.split()
        rest = tokens[1:]  # 去掉跳数

        # 提取三个探测值：* / <1 ms / N ms / N 毫秒
        probes = []
        idx = 0
        while idx < len(rest):
            t = rest[idx]
            # 已收集满 3 个 probe，且当前 token 不是 probe 后缀 → 退出
            if len(probes) >= 3 and t not in ("ms", "毫秒"):
                break
            if len(probes) >= 3 and t in ("ms", "毫秒"):
                # 为最后一个 probe 追加 ms 后缀
                if probes[-1] is not None:
                    probes[-1] = probes[-1] + " " + t
                idx += 1
                continue
            if t == "*":
                probes.append(None)
                idx += 1
            elif t in ("ms", "毫秒") and probes:
                # 追加到上一个探测值
                if probes[-1] is not None:
                    probes[-1] = probes[-1] + " " + t
                idx += 1
            elif t.replace(".", "", 1).isdigit() or t.lstrip("<").isdigit():
                probes.append(t)
                idx += 1
            else:
                break

        target = " ".join(rest[idx:]).strip()
        # 去掉尾部超时提示
        target = re.sub(r"\s*请求超时。?$", "", target).strip()
        target = re.sub(r"\s*Request timed out\.?$", "", target).strip()

        hops.append({
            "hop": hop_num,
            "probes": probes,
            "target": target,
            "all_timeout": all(p is None for p in probes),
        })
    return hops


def analyze_diag(tracert_out: str, nslookup_out: str) -> Dict:
    """分析诊断结果，返回结论字典"""
    result = {
        "conclusion": "",
        "broken_hop": None,
        "dns_ok": False,
        "tracert_reached_target": False,
    }

    # 分析 nslookup
    result["dns_ok"] = "Name:" in nslookup_out or "名称:" in nslookup_out

    # 分析 tracert
    if not tracert_out or tracert_out.startswith("[tracert"):
        if result["dns_ok"]:
            if "超时" in tracert_out:
                result["conclusion"] = "tracert 执行超时，但DNS正常。故障可能在路由层（防火墙拦截tracert或上游路由无响应）"
            else:
                result["conclusion"] = "tracert 执行失败，但DNS正常。故障可能不在DNS层面"
        else:
            if "超时" in tracert_out:
                result["conclusion"] = "tracert 执行超时，DNS也不可达。故障可能在网关或上游链路"
            else:
                result["conclusion"] = "诊断工具执行失败，无法分析故障点"
        return result

    hops = _parse_tracert_hops(tracert_out)
    if not hops:
        # tracert 可能没有跳数输出（全超时）
        result["conclusion"] = "tracert 全超时，整条链路断开（可能为网关/物理层故障）"
        return result

    first_timeout_hop = None
    last_ok_hop = None
    for h in hops:
        if h["all_timeout"]:
            if first_timeout_hop is None:
                first_timeout_hop = h["hop"]
        else:
            last_ok_hop = h["hop"]

    last_hop = hops[-1]
    result["tracert_reached_target"] = not last_hop["all_timeout"]

    dns_status = "DNS正常" if result["dns_ok"] else "DNS解析失败"

    if first_timeout_hop is None or not first_timeout_hop:
        # 全部有响应
        if result["dns_ok"]:
            result["conclusion"] = "链路可达，DNS正常，故障可能在目标服务器或应用层"
        else:
            result["conclusion"] = "链路可达但DNS异常，故障可能在DNS服务器或上游链路"
    elif first_timeout_hop == 1:
        result["broken_hop"] = 1
        result["conclusion"] = "断在第1跳（网关无响应），%s，故障可能在本机网卡或路由器" % dns_status
    elif last_ok_hop and first_timeout_hop:
        result["broken_hop"] = first_timeout_hop
        result["conclusion"] = "断在第%d跳（%s之后），%s，故障可能在路由%d或上游链路" % (
            first_timeout_hop, "路由%d" % last_ok_hop if last_ok_hop else "网关",
            dns_status, first_timeout_hop)
    else:
        result["broken_hop"] = first_timeout_hop
        result["conclusion"] = "链路异常（断在第%d跳），%s" % (first_timeout_hop, dns_status)
    return result


# ── 检测引擎 ────────────────────────────────────────────────────

CHECK_INTERVAL = 10          # 检测间隔（秒）
OFFLINE_THRESHOLD = 3        # 连续失败次数判定断线
ONLINE_THRESHOLD = 2         # 连续成功次数判定恢复

CHECK_TARGETS = [
    ("114.114.114.114", "DNS"),
    ("www.baidu.com", "公网"),
]


class NetworkMonitor:
    """
    网络故障检测器。

    用法:
        monitor = NetworkMonitor()
        monitor.start()
        ...
        monitor.stop()

    后台线程每 CHECK_INTERVAL 秒检测一次连通性链：
      本机(loopback) → 网关(route) → DNS → 公网
    根据失败位置确定 hop_count。
    """

    def __init__(self):
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

        # 状态
        self._fail_count = 0          # 连续失败次数
        self._success_count = 0       # 连续成功次数
        self._is_offline = False      # 当前是否断线状态
        self._offline_event_id: Optional[int] = None  # 未恢复事件的 id
        self._last_offline_start: Optional[str] = None
        self._last_gateway: str = ""
        self._last_hop_count: int = 0
        self._offline_triggered = False  # 是否已写入 offline 事件（防止重复写）

        # 确保数据库就绪
        get_db().close()

    # ── 生命周期 ──────────────────────────────────────────────

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True,
            name="network-monitor"
        )
        self._thread.start()
        log.info("[网络监控] 已启动，间隔 %d 秒", CHECK_INTERVAL)

    def stop(self):
        self._stop_event.set()
        # 如果断线中，先记录恢复（强制结束）
        if self._is_offline:
            self._write_recovery()
        log.info("[网络监控] 已停止")

    # ── 主循环 ────────────────────────────────────────────────

    def _run_loop(self):
        while not self._stop_event.is_set():
            try:
                self._check_once()
            except Exception as e:
                log.warning("[网络监控] 检测异常: %s", e)
            self._stop_event.wait(CHECK_INTERVAL)

    def _check_once(self):
        """执行一轮检测"""
        gw = _get_gateway()
        self._last_gateway = gw or ""

        # 检测链：本机 → 网关 → DNS → 公网
        hop = 0  # hop_count

        # 第一步：本机网卡（ping 127.0.0.1）
        if not _ping("127.0.0.1", timeout=1):
            hop = 0
            err = "本机网卡不可达"
            self._on_failure(hop, gw, err)
            return

        # 第二步：网关（如果有）
        if gw:
            if not _ping(gw, timeout=2):
                hop = 1
                err = "网关不可达: %s" % gw
                self._on_failure(hop, gw, err)
                return

        # 第三步：DNS / 公网
        all_ok = True
        fail_reason = ""
        for target, name in CHECK_TARGETS:
            if not _ping(target, timeout=3):
                all_ok = False
                fail_reason = "%s 不可达: %s" % (name, target)
                break

        if all_ok:
            self._on_success()
        else:
            hop = 2 if gw else 1
            self._on_failure(hop, gw, fail_reason)

    # ── 状态处理 ──────────────────────────────────────────────

    def _on_failure(self, hop: int, gateway: str, error: str):
        self._fail_count += 1
        self._success_count = 0
        self._last_hop_count = hop

        if self._fail_count >= OFFLINE_THRESHOLD and not self._is_offline:
            # 从正常 → 断线
            self._is_offline = True
            self._offline_triggered = False
            self._last_offline_start = _now()
            log.warning("[网络监控] 断线 detected (hop=%d): %s", hop, error)
            self._write_offline(hop, gateway, error)
            # 异步触发诊断（不阻塞主循环）
            eid = self._offline_event_id
            if eid:
                threading.Thread(target=self._run_diagnostics,
                                 args=(eid,), daemon=True).start()

        elif self._is_offline and not self._offline_triggered:
            # 已在断线中，更新错误信息（只记录一次，避免刷日志）
            self._offline_triggered = True

        if self._is_offline:
            log.debug("[网络监控] 仍断线 (hop=%d): %s", hop, error)

    def _on_success(self):
        self._success_count += 1
        self._fail_count = 0

        if self._is_offline and self._success_count >= ONLINE_THRESHOLD:
            # 从断线 → 恢复
            log.info("[网络监控] 网络已恢复")
            self._write_recovery()
            self._is_offline = False
            self._offline_event_id = None
            self._offline_triggered = False

    # ── 数据库写入 ────────────────────────────────────────────

    def _write_offline(self, hop: int, gateway: str, error: str):
        conn = get_db()
        try:
            cur = conn.execute(INSERT_SQL, (
                "offline",
                _now(),
                None,        # end_time（恢复时回写）
                None,        # duration_seconds
                gateway,
                "",
                error,
                hop,
            ))
            conn.commit()
            self._offline_event_id = cur.lastrowid
        finally:
            conn.close()

    def _write_recovery(self):
        if self._offline_event_id is None:
            return
        now = _now()
        # 从最后一个 offline 事件的 start_time 算 duration
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT start_time FROM network_events WHERE id = ?",
                (self._offline_event_id,)
            ).fetchone()
            if row:
                try:
                    start_ts = time.mktime(time.strptime(row["start_time"], "%Y-%m-%d %H:%M:%S"))
                    duration = int(time.time() - start_ts)
                except Exception:
                    duration = 0
                conn.execute(UPDATE_END_SQL, (now, duration, self._offline_event_id))
                conn.commit()
                log.info("[网络监控] 断线恢复，持续 %d 秒", duration)
                # 异步触发恢复后诊断
                eid = self._offline_event_id
                threading.Thread(target=self._run_recovery_diag,
                                 args=(eid,), daemon=True).start()
        finally:
            conn.close()
        self._offline_event_id = None

    # ── 自动诊断 ──────────────────────────────────────────────

    def _run_diagnostics(self, event_id: int):
        """断线后执行 tracert + nslookup，分析故障点，写入数据库"""
        log.info("[网络监控] 开始断线诊断 (event_id=%d)...", event_id)
        tracert_out = ""
        nslookup_out = ""
        conclusion = "诊断未完成"
        try:
            # 单个目标、短超时，避免诊断过程拖太久
            tgt = DIAG_TARGETS[0]
            log.info("[诊断] 执行 tracert %s ...", tgt)
            out = run_tracert(tgt)
            log.info("[诊断] tracert 完成, return=%s, 长度=%d", out[:60] if len(out) > 60 else out, len(out))
            if out and not out.startswith("[tracert"):
                tracert_out = out
            else:
                tracert_out = out  # 保留超时/错误信息，用于 analyze_diag 判断

            log.info("[诊断] 执行 nslookup ...")
            nslookup_out = run_nslookup(DIAG_DOMAIN)
            log.info("[诊断] nslookup 完成, 前200字: %s", nslookup_out[:200] if len(nslookup_out) > 200 else nslookup_out)

            result = analyze_diag(tracert_out, nslookup_out)
            conclusion = result["conclusion"]
        except Exception as e:
            conclusion = "诊断异常: %s" % e
            log.warning("[诊断] 诊断过程异常: %s", e, exc_info=True)

        # 确保写入数据库
        log.info("[诊断] 准备写入: event_id=%d, conclusion=%s, tracert_len=%d, nslookup_len=%d",
                 event_id, conclusion, len(tracert_out or ""), len(nslookup_out or ""))
        try:
            conn = get_db()
            try:
                conn.execute(UPDATE_DIAG_SQL, (
                    tracert_out, nslookup_out, conclusion, event_id
                ))
                conn.commit()
                # 验证写入
                check = conn.execute(
                    "SELECT diag_conclusion, diag_nslookup FROM network_events WHERE id = ?",
                    (event_id,)
                ).fetchone()
                if check:
                    log.info("[诊断] 写入验证: diag_conclusion=%s, diag_nslookup_len=%d",
                             check["diag_conclusion"], len(check["diag_nslookup"] or ""))
                else:
                    log.warning("[诊断] 写入验证: event_id=%d 未找到!", event_id)
            finally:
                conn.close()
        except Exception as e:
            log.warning("[诊断] 写入诊断结果失败: %s", e)

        log.info("[网络监控] 诊断完成 (event=%d): %s", event_id, conclusion)

    def _run_recovery_diag(self, event_id: int):
        """恢复后快速诊断，判断根因"""
        log.info("[网络监控] 开始恢复后诊断 (event_id=%d)...", event_id)
        recovery_tracert = run_tracert(DIAG_TARGETS[0])
        # 尝试读取断线时的诊断结论
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT diag_conclusion FROM network_events WHERE id = ?",
                (event_id,)
            ).fetchone()
            old_conclusion = row["diag_conclusion"] if row else ""
        except Exception:
            old_conclusion = ""
        finally:
            conn.close()

        root_cause = "故障已自动恢复"
        if "tracert 全超时" in old_conclusion:
            root_cause = "链路抖动（整条链路短暂中断后自动恢复）"
        elif "断在第" in old_conclusion:
            root_cause = "链路抖动（上游路由短暂中断后自动恢复）"
        elif "链路可达但DNS" in old_conclusion:
            root_cause = "DNS服务器瞬断"

        conn = get_db()
        try:
            conn.execute(UPDATE_RECOVERY_SQL, (recovery_tracert, root_cause, event_id))
            conn.commit()
        finally:
            conn.close()
        log.info("[网络监控] 恢复诊断完成 (event=%d): %s", event_id, root_cause)

    # ── 外部查询 ──────────────────────────────────────────────

    @property
    def is_offline(self) -> bool:
        return self._is_offline

    @property
    def last_hop_count(self) -> int:
        return self._last_hop_count

    @property
    def last_error(self) -> str:
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT error_message FROM network_events WHERE event_type='offline' AND end_time IS NULL ORDER BY id DESC LIMIT 1"
            ).fetchone()
            return row["error_message"] if row else ""
        finally:
            conn.close()
