"""
目标驱动探测模块 v1.3.0：
- 启动时从服务端拉取 targets 配置
- 按 targets 配置执行探测（ping / http / port / dns）
- 本地缓存 targets，无网络时用缓存运行
- 定期重新拉取配置
"""
import os, json, time, logging
from typing import List, Dict, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

from core.config import CONFIG_DIR, CONFIG_FILE
from core.transport import Transport

log = logging.getLogger("target_runner")

CACHE_FILE = os.path.join(CONFIG_DIR, "targets_cache.json")
DEFAULT_INTERVAL = 300  # 5分钟重新拉取配置


def _load_cache() -> Optional[Dict]:
    if not os.path.exists(CACHE_FILE):
        return None
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save_cache(targets: List[Dict]):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "targets": targets,
            }, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.warning("保存 targets 缓存失败: %s", e)


def _run_ping(target: str, timeout: int = 5) -> Dict:
    """执行单次 ping，返回 dict"""
    import subprocess, re, sys
    try:
        if sys.platform == "win32":
            out, _ = subprocess.run(
                f'ping -n 1 -w {timeout*1000} {target}',
                capture_output=True, text=True, timeout=timeout + 2,
                shell=True
            )
            text = out
            m = re.search(r'[Aa]verage\s*=\s*(\d+)ms', text)
            if m:
                return {"status": "ok", "rtt_ms": float(m.group(1))}
            if "TTL=" in text.upper():
                return {"status": "ok", "rtt_ms": 0.0}
            return {"status": "unreachable", "rtt_ms": None}
        else:
            out, _ = subprocess.run(
                f'ping -c 1 -W {timeout} {target}',
                capture_output=True, text=True, timeout=timeout + 2,
                shell=False
            )
            text = out
            m = re.search(r'time[=<](\d+\.?\d*)', text)
            if m:
                return {"status": "ok", "rtt_ms": float(m.group(1))}
            return {"status": "unreachable", "rtt_ms": None}
    except Exception as e:
        return {"status": "error", "rtt_ms": None, "error": str(e)}


def _run_http(target: str, port: int = 80, timeout: int = 5) -> Dict:
    """执行 HTTP 健康检查"""
    import httpx
    schema = "https" if port == 443 else "http"
    url = f"{schema}://{target}" if not target.startswith("http") else target
    try:
        start = time.time()
        r = httpx.get(url, timeout=timeout, follow_redirects=True,
                      headers={"User-Agent": "LanwatchAgent/1.3.0"})
        rtt_ms = (time.time() - start) * 1000
        return {
            "status": "ok" if r.status_code < 500 else "error",
            "status_code": r.status_code,
            "rtt_ms": round(rtt_ms, 2),
        }
    except httpx.TimeoutException:
        return {"status": "timeout", "rtt_ms": None, "status_code": None}
    except Exception as e:
        return {"status": "error", "rtt_ms": None, "error": str(e), "status_code": None}


def _run_port(target: str, port: int, timeout: int = 3) -> Dict:
    """执行 TCP 端口检测"""
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        result = sock.connect_ex((target, port))
        sock.close()
        return {"status": "open" if result == 0 else "closed", "port": port}
    except Exception as e:
        return {"status": "error", "port": port, "error": str(e)}


def _run_dns(target: str, timeout: int = 5) -> Dict:
    """执行 DNS 解析"""
    import socket
    try:
        start = time.time()
        ip = socket.gethostbyname(target)
        rtt_ms = (time.time() - start) * 1000
        return {"status": "ok", "ip": ip, "rtt_ms": round(rtt_ms, 2)}
    except socket.gaierror:
        return {"status": "error", "error": "DNS解析失败"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def run_probe_for_target(target_cfg: Dict) -> Dict:
    """根据 target 配置执行对应探测，返回探测结果"""
    probe_type = target_cfg.get("probe_type", "ping")
    target = target_cfg.get("target", "")
    timeout = target_cfg.get("timeout", 5)

    if not target:
        return None

    if probe_type == "ping":
        result = _run_ping(target, timeout)
    elif probe_type == "http":
        result = _run_http(target, target_cfg.get("port", 80), timeout)
    elif probe_type == "port":
        result = _run_port(target, target_cfg.get("port", 80), timeout)
    elif probe_type == "dns":
        result = _run_dns(target, timeout)
    else:
        log.warning("未知探测类型: %s，跳过", probe_type)
        return None

    return {
        "probe_type": probe_type,
        "target": target,
        "name": target_cfg.get("name", ""),
        "interval": target_cfg.get("interval", 60),
        **result,
    }


def run_all_probes(targets: List[Dict]) -> List[Dict]:
    """对所有 targets 并行执行探测，返回结果列表"""
    results = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(run_probe_for_target, t): t for t in targets if t.get("enabled", True)}
        for future in as_completed(futures):
            try:
                r = future.result()
                if r:
                    results.append(r)
            except Exception as e:
                log.warning("探测执行异常: %s", e)
    return results


class TargetRunner:
    """
    目标驱动运行器：
    - 启动时拉取 targets
    - 按配置执行探测并上报
    - 定期刷新 targets 配置
    """

    def __init__(self, server_url: str, agent_id: str, agent_token: str, refresh_interval: int = DEFAULT_INTERVAL):
        self.server_url = server_url
        self.agent_id = agent_id
        self.agent_token = agent_token
        self.refresh_interval = refresh_interval
        self._targets: List[Dict] = []
        self._last_refresh = 0.0
        self._transport = None

    def _get_transport(self) -> Optional[Transport]:
        if self._transport is None:
            self._transport = Transport(self.server_url, self.agent_id, self.agent_token)
        return self._transport

    def fetch_targets(self, use_cache: bool = True) -> List[Dict]:
        """
        从服务端拉取 targets 配置。
        失败时返回缓存（如果有）。
        """
        # 先尝试缓存
        if use_cache:
            cached = _load_cache()
            if cached and cached.get("targets"):
                self._targets = cached["targets"]
                log.info("[Targets] 使用缓存 (%d 个目标)", len(self._targets))

        # 拉取服务端配置
        try:
            transport = self._get_transport()
            targets = transport.fetch_targets()
            if targets is not None:
                self._targets = targets
                _save_cache(targets)
                self._last_refresh = time.time()
                log.info("[Targets] 从服务端拉取成功 (%d 个目标)", len(targets))
                return targets
        except Exception as e:
            log.warning("[Targets] 拉取失败: %s", e)

        # 拉取失败且无缓存
        if not self._targets:
            log.warning("[Targets] 无可用配置，探测将不执行")
        return self._targets

    def should_refresh(self) -> bool:
        return (time.time() - self._last_refresh) >= self.refresh_interval

    def run_once(self) -> List[Dict]:
        """执行一次探测循环（先检查是否需要刷新配置）"""
        if self.should_refresh():
            self.fetch_targets()

        if not self._targets:
            log.debug("[Targets] 没有配置目标，跳过本次探测")
            return []

        return run_all_probes(self._targets)

    def report_results(self, results: List[Dict]) -> bool:
        """上报探测结果到服务端"""
        if not results:
            return True
        try:
            transport = self._get_transport()
            ok = transport.report(results)
            if ok:
                log.info("[上报] 成功 %d 条探测结果", len(results))
            else:
                log.warning("[上报] 失败")
            return ok
        except Exception as e:
            log.error("[上报] 异常: %s", e)
            return False

    def close(self):
        if self._transport:
            self._transport.close()
            self._transport = None