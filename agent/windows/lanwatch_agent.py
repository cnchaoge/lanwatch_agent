#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lanwatch_agent - 企业网络监控客户端 v0.8.0"""

__version__ = "0.8.1"

import tempfile

# ═══════════════════════════════════════════════════════════════
# 自动升级配置
# ═══════════════════════════════════════════════════════════════
UPDATE_CHECK_INTERVAL = 86400   # 检查频率：每天一次（秒）
GITHUB_REPO = "cnchaoge/lanwatch_agent"
UPDATE_MARKER_FILE = os.path.expanduser("~/.lanwatch_agent_update.json")
UPDATE_HELPER = os.path.join(tempfile.gettempdir(), "lanwatch_update_helper.py")

# ═══════════════════════════════════════════════════════════════
# 自动升级功能
# ═══════════════════════════════════════════════════════════════

def check_github_latest_version():
    """从 GitHub releases API 获取最新版本号，返回 (version, download_url) 或 None"""
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
            headers={"User-Agent": "lanwatch_agent"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            tag = data.get("tag_name", "").strip()
            if tag.startswith("v"):
                version = tag[1:]
            else:
                version = tag
            download_url = None
            for asset in data.get("assets", []):
                if asset.get("name") == "lanwatch_agent.exe":
                    download_url = asset.get("browser_download_url")
                    break
            if download_url and version:
                return version, download_url
    except Exception as e:
        log.debug("[升级] 检查失败: %s", e)
    return None


def parse_version(v):
    """将版本字符串转为 (int, int, int) 元组，用于比较"""
    try:
        parts = v.strip().lstrip("v").split(".")
        return tuple(int(p) for p in parts[:3]) + (0, 0, 0)[:3-len(parts)]
    except Exception:
        return (0, 0, 0)


def _write_update_helper_script(exe_path, marker_path, marker_data):
    """生成升级辅助脚本，用于复制新 exe 并重启"""
    helper = UPDATE_HELPER
    try:
        with open(helper, "w", encoding="utf-8") as f:
            f.write(f"""
import sys, os, time, shutil, json

marker = {marker_data!r}
with open({marker_path!r}, 'r') as mf:
    info = json.load(mf)
dst = info['dst']
src = info['src']

# 等待原进程退出
for _ in range(15):
    try:
        shutil.copy2(src, dst)
        break
    except Exception:
        time.sleep(1)

# 清理标记文件
try: os.remove({marker_path!r})
except Exception: pass

# 重启
try:
    os.system(f'"{{dst}}"')
except Exception:
    pass
""")
        log.debug("[升级] 辅助脚本已写入: %s", helper)
    except Exception as e:
        log.warning("[升级] 写入辅助脚本失败: %s", e)


def _do_upgrade(download_url, new_version):
    """下载新版本 exe 并触发升级"""
    log.info("[升级] 准备下载新版本 v%s ...", new_version)
    try:
        req = urllib.request.Request(download_url, headers={"User-Agent": "lanwatch_agent"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
        log.info("[升级] 下载完成，大小: %s", len(data))

        # 写到 temp 目录
        tmp_exe = os.path.join(tempfile.gettempdir(), "lanwatch_agent_new.exe")
        with open(tmp_exe, "wb") as f:
            f.write(data)
        log.info("[升级] 临时文件: %s", tmp_exe)

        # 标记文件，helper 会读取目标路径
        import random
        marker_path = os.path.join(tempfile.gettempdir(), f"lw_update_{random.randint(100000,999999)}.json")
        dst_exe = sys.executable
        marker_data = {"src": tmp_exe, "dst": dst_exe}
        with open(marker_path, "w") as f:
            json.dump(marker_data, f)

        # 生成辅助脚本
        _write_update_helper_script(tmp_exe, marker_path, marker_data)

        # 启动辅助脚本后，本进程退出
        log.info("[升级] 正在替换并重启...")
        try:
            import subprocess
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = subprocess.SW_HIDE
            subprocess.Popen(
                [sys.executable, UPDATE_HELPER],
                startupinfo=si
            )
        except Exception as e:
            log.error("[升级] 启动辅助脚本失败: %s", e)
            return

        # 退出当前程序
        os._exit(0)
    except Exception as e:
        log.error("[升级] 下载/替换失败: %s", e)


def check_and_upgrade():
    """检查新版本并提示用户升级"""
    try:
        result = check_github_latest_version()
        if not result:
            _show_upgrade_toast("检查失败", "无法连接到 GitHub，请稍后重试")
            return
        new_version, download_url = result
        if parse_version(new_version) <= parse_version(__version__):
            _show_upgrade_toast("已是最新", f"当前 v{__version__} 已是最新版本")
            return
        log.info("[升级] 发现新版本 v%s（当前 v%s）", new_version, __version__)
        _notify_upgrade(new_version, download_url)
    except Exception as e:
        log.warning("[升级] 检查异常: %s", e)


def _do_manual_upgrade_check():
    """手动检查更新（托盘菜单调用）"""
    threading.Thread(target=check_and_upgrade, daemon=True, name="upgrade_check_manual").start()


def _show_upgrade_toast(title, msg):
    """在托盘线程中弹出提示（无需用户交互的结果通知）"""
    def _popup():
        try:
            from tkinter import messagebox
            root = _tk_root
            if root is None:
                return
            messagebox.showinfo(title, msg, parent=root)
        except Exception:
            pass
    if _tk_root:
        _tk_root.after(0, _popup)


def _notify_upgrade(new_version, download_url):
    """在托盘线程中弹出升级提示"""
    def _popup():
        try:
            from tkinter import messagebox
            root = _tk_root
            if root is None:
                return
            if messagebox.askyesno(
                "发现新版本",
                f"发现新版本 v{new_version}（当前 v{__version__}）\n\n是否立即下载并升级？\n\n"
                f"升级过程将自动重启客户端",
                parent=root
            ):
                log.info("[升级] 用户确认，开始下载...")
                threading.Thread(target=_do_upgrade, args=(download_url, new_version), daemon=True).start()
            else:
                log.info("[升级] 用户取消升级")
        except Exception as e:
            log.warning("[升级] 弹窗失败: %s", e)
    if _tk_root:
        _tk_root.after(0, _popup)

import socket
from time import sleep
import time
import json
import sys
import os
import uuid
import logging
import subprocess
import urllib.request
import urllib.error
import threading
import ctypes
import queue
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import json
import sys
import os
import uuid
import logging
import subprocess
import urllib.request
import urllib.error
import threading
import ctypes
import queue
import tempfile
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

# ═══════════════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════════════
SERVER_URL = "http://82.156.229.67:8000"
REPORT_INTERVAL = 60
TOPOLOGY_INTERVAL = 300       # 5 分钟扫一次拓扑
LOG_FILE = os.path.expanduser("~/.lanwatch_agent.log")
CONFIG_FILE = os.path.expanduser("~/.lanwatch_agent.json")

# ═══════════════════════════════════════════════════════════════
# 日志
# ═══════════════════════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger()

# ═══════════════════════════════════════════════════════════════
# 全局状态（线程安全）
# ═══════════════════════════════════════════════════════════════
_status_queue = queue.Queue()  # 托盘状态更新队列（跨线程通信）
_action_queue = queue.Queue()  # 跨线程动作队列（卸载等需主线程处理）
_tray_icon_ref = None
_winreg = None          # 动态导入，Windows 专用
_executor = None        # 拓扑扫描线程池
_status_thread_started = False  # 托盘状态轮询线程只启动一次
_tk_root = None        # 隐藏的 Tk 主窗口（用于跨线程安全调用）
consecutive_errors = 0  # 连续上报失败次数

# ═══════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════

def _run_hidden(cmd, timeout=5):
    """静默执行系统命令，隐藏黑窗口"""
    try:
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = subprocess.SW_HIDE
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout, startupinfo=si
        )
        return result.stdout, result.stderr
    except Exception:
        return "", ""


def get_local_ip():
    """获取本机默认网卡 IP"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        pass
    # 备用方案：Windows 用 ipconfig 提取
    try:
        import subprocess
        out = subprocess.check_output("ipconfig", stderr=subprocess.DEVNULL, text=True)
        for line in out.splitlines():
            if "IPv4" in line:
                parts = line.split(":")
                if len(parts) >= 2:
                    ip = parts[1].strip()
                    if ip and ip != "0.0.0.0":
                        return ip
    except Exception:
        pass
    return ""


def get_subnet_prefix():
    """从本机 IP 推断网段前缀，如 192.168.1"""
    ip = get_local_ip()
    if not ip:
        return ""
    parts = ip.rsplit(".", 1)
    return parts[0]  # e.g. 192.168.1.23 → 192.168.1


def get_gateway():
    """获取本机默认网关，优先从 route print 读取，回退到 .1 规则"""
    try:
        if sys.platform == "win32":
            import subprocess, re as _re
            out = subprocess.check_output(
                "route print -4", shell=True, stderr=subprocess.DEVNULL, text=True
            )
            for line in out.splitlines():
                line = line.strip()
                parts = _re.split(r"\s+", line)
                if len(parts) >= 3 and parts[0] == "0.0.0.0" and _re.match(r"^\d+\.\d+\.\d+\.\d+$", parts[2]):
                    return parts[2]
    except Exception:
        pass
    ip = get_local_ip()
    if not ip:
        return "192.168.1.1"
    parts = ip.rsplit(".", 1)
    return parts[0] + ".1"


# ═══════════════════════════════════════════════════════════════
# 配置读写
# ═══════════════════════════════════════════════════════════════

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return None


def save_config(cfg):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.error("保存配置失败: %s", e)


# ═══════════════════════════════════════════════════════════════
# 探测函数（核心）
# ═══════════════════════════════════════════════════════════════

def ping_once(host, timeout=3):
    """用 ICMP ping 探测主机是否可达，返回延迟ms；失败返回 None"""
    try:
        if sys.platform == "win32":
            out, _ = _run_hidden(f'ping -n 1 -w {timeout*1000} {host}')
            if "TTL=" in out.upper():
                # 优先取 Average 时间，格式: Average = Xms（英文 Windows）
                m = re.search(r'[Aa]verage\s*=\s*(\d+)ms', out)
                if m:
                    return float(m.group(1))
                # time=Xms（英文）或 时间=Xms（中文 Windows）
                m = re.search(r'[Tt]ime[=<]?\s*(\d+\.?\d*)\s*ms', out)
                if m:
                    return float(m.group(1))
                m = re.search(r'时间[=<]?\s*(\d+\.?\d*)\s*ms', out)
                if m:
                    return float(m.group(1))
                # 有 TTL 响应但读不到时间（某些 Windows 变体），返回 1ms
                return 1.0
            return None
        else:
            out, _ = _run_hidden(f'ping -c 1 -W {timeout} {host}')
            if "1 packets transmitted, 1 received" in out or "1 received" in out:
                m = re.search(r'time[=<](\d+\.?\d*)', out)
                return float(m.group(1)) if m else None
            return None
    except Exception:
        return None


def ping_multi(host, count=3, timeout=2):
    """
    多次 Ping，计算丢包率和平均延迟
    优先用 ICMP，真正可用的探测方式
    """
    rtts = []
    for _ in range(count):
        rtt = ping_once(host, timeout=timeout)
        if rtt is not None:
            rtts.append(rtt)
        sleep(0.3)
    loss = (count - len(rtts)) / count * 100
    avg_rtt = sum(rtts) / len(rtts) if rtts else None
    return bool(rtts), avg_rtt, loss


def measure_dns_single(host):
    """测单个域名 DNS 解析延迟"""
    try:
        start = time.time()
        socket.gethostbyname(host)
        return (time.time() - start) * 1000
    except Exception:
        return None


def measure_dns_multi():
    """测多个 DNS 服务器质量（百度/阿里/腾讯/网易）"""
    hosts = {
        "dns_baidu": "www.baidu.com",
        "dns_ali": "www.aliyun.com",
        "dns_tencent": "www.qq.com",
        "dns_163": "www.163.com",
    }
    return {k: measure_dns_single(h) for k, h in hosts.items()}


# ═══════════════════════════════════════════════════════════════
# MAC 地址获取（正确实现）
# ═══════════════════════════════════════════════════════════════

def get_mac_for_ip(ip):
    """
    向目标 IP 发送 ARP 请求（Windows: arp -a 之前先用 ping 触发 ARP 缓存）
    返回 MAC 地址字符串，失败返回 ""
    """
    try:
        if sys.platform == "win32":
            # 先 ping（触发 ARP），再查 ARP 表
            _run_hidden(f'ping -n 1 -w 300 {ip}', timeout=2)
            out, _ = _run_hidden(f'arp -a {ip}')
            # 格式如: 192.168.1.1    60:de:44:67:12:1a     动态
            m = re.search(r'([0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}', out)
            if m:
                return m.group(0).replace("-", ":").upper()
            # 尝试全量 ARP 表
            out_all, _ = _run_hidden('arp -a')
            for line in out_all.splitlines():
                if ip in line:
                    m2 = re.search(r'([0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}', line)
                    if m2:
                        return m2.group(0).replace("-", ":").upper()
        else:
            # Linux: 先 ping，再查 arp -a
            _run_hidden(f'ping -c 1 -W 1 {ip}', timeout=2)
            out, _ = _run_hidden(f'arp -a -n {ip}')
            m = re.search(r'([0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}', out)
            if m:
                return m.group(0).replace("-", ":").upper()
    except Exception as e:
        log.debug("MAC lookup failed for %s: %s", ip, e)
    return ""


def get_local_mac():
    """获取本机 MAC 地址（所有网卡，返回第一个有效的）"""
    try:
        if sys.platform == "win32":
            out, _ = _run_hidden('getmac /v /fo csv /nh')
            for line in out.splitlines():
                line = line.strip()
                if not line:
                    continue
                parts = [p.strip().strip('"') for p in line.split(",")]
                # 格式: 连接名称, 网络适配器, MAC, 传输类型
                if len(parts) >= 3:
                    mac = parts[2]
                    if re.match(r'^([0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}$', mac):
                        return mac.upper().replace("-", ":")
        else:
            out, _ = _run_hidden("ip link show")
            for line in out.splitlines():
                m = re.search(r'link/ether ([0-9a-f:]+)', line)
                if m:
                    return m.group(1).upper()
    except Exception:
        pass
    return ""


# ═══════════════════════════════════════════════════════════════
# 厂商识别
# ═══════════════════════════════════════════════════════════════

OUI_VENDOR = {
    "00:50:56": "VMware",   "00:0C:29": "VMware",   "00:1C:14": "VMware",
    "00:05:69": "VMware",
    "00:14:6C": "NetGear", "00:50:BA": "NetGear",
    "00:1B:2B": "HP",      "00:1F:29": "HP",       "00:21:5A": "HP",
    "00:22:64": "Dell",    "00:06:5B": "Dell",
    "00:1C:B3": "Apple",   "00:1D:4F": "Apple",    "00:1E:C9": "Apple",
    "00:1E:52": "Cisco",   "00:1A:2B": "Cisco",    "00:25:84": "Cisco",
    "00:04:4B": "Nvidia",
    "00:1A:11": "Google",
    "00:50:F2": "Microsoft","00:0D:3A": "Microsoft","00:12:5A": "Microsoft",
    "00:15:5D": "Microsoft","00:17:FA": "Microsoft",
    "00:1A:6B": "TP-Link", "00:27:19": "TP-Link",  "14:CC:20": "TP-Link",
    "30:B5:C2": "TP-Link",
    "00:25:9E": "Cisco-Linksys","00:1A:70": "Cisco-Linksys",
    "00:1E:58": "D-Link",  "00:22:B0": "D-Link",   "00:26:5A": "D-Link",
    "1C:AF:F7": "D-Link",
    "00:24:B2": "ZTE",     "00:1B:3C": "ZTE",     "44:2A:60": "ZTE",
    "00:25:68": "Huawei",  "00:18:82": "Huawei",   "00:1E:10": "Huawei",
    "34:29:12": "Huawei",
    "20:CF:30": "Xiaomi", "34:80:B3": "Xiaomi",   "F8:A4:5F": "Xiaomi",
    "C8:D7:B0": "Xiaomi",
    "18:31:BF": "Huawei", "88:53:95": "Huawei",
    "08:00:27": "VirtualBox",
    "00:1C:42": "Parallels",
    "00:16:3E": "Xensource",
}


def get_vendor(mac):
    if not mac:
        return ""
    prefix = mac.upper().replace("-", ":")[:8]
    return OUI_VENDOR.get(prefix, "")


def guess_device_type(hostname="", vendor="", mac=""):
    h = hostname.lower()
    v = vendor.lower()
    if any(k in h for k in ["router","gateway","tplink","netgear","tendawifi","mercury","mi"]):
        return "router"
    if any(k in h for k in ["printer","print","hp","canon","brother","epson"]):
        return "printer"
    if any(k in h for k in ["server","nas","synology","qnap","群晖"]):
        return "server"
    if any(k in h for k in ["switch","sw"]):
        return "switch"
    if "cisco" in v: return "router"
    if "hp" in v: return "switch"
    if "dell" in v: return "server"
    if "vmware" in v or "virtualbox" in v: return "vm"
    if "apple" in v: return "phone"
    if "xiaomi" in v or "huawei" in v or "zte" in v or "tp-link" in v: return "router"
    return "unknown"


# ═══════════════════════════════════════════════════════════════
# 拓扑扫描（多线程并发）
# ═══════════════════════════════════════════════════════════════

def _probe_host(ip):
    """探测单个 IP 是否存活（ICMP ping），返回 (ip, mac, hostname) 或 None"""
    rtt = ping_once(ip, timeout=1)
    if rtt is not None:
        mac = get_mac_for_ip(ip)
        hostname = _resolve_hostname(ip)
        return (ip, mac, hostname)
    return None


def _resolve_hostname(ip):
    """尝试反解主机名"""
    try:
        name, _, _ = socket.gethostbyaddr(ip)
        return name
    except Exception:
        return ""



# ═══════════════════════════════════════════════════════════════
# 端口扫描（常见服务识别）
# ═══════════════════════════════════════════════════════════════

# 常见端口及服务名（按实用频率排序）
COMMON_PORTS = [
    (21, "ftp"),
    (22, "ssh"),
    (23, "telnet"),
    (25, "smtp"),
    (53, "dns"),
    (80, "http"),
    (110, "pop3"),
    (111, "rpcbind"),
    (135, "msrpc"),
    (139, "netbios"),
    (143, "imap"),
    (443, "https"),
    (445, "smb"),
    (465, "smtps"),
    (502, "modbus"),
    (503, "abbach"),
    (543, "postgresql"),
    (587, "smtp"),
    (993, "imaps"),
    (995, "pop3s"),
    (1080, "socks"),
    (1433, "mssql"),
    (1521, "oracle"),
    (1723, "pptp"),
    (1883, "mqtt"),
    (2375, "docker"),
    (3000, "http"),
    (3306, "mysql"),
    (3389, "rdp"),
    (4000, "http"),
    (5000, "http"),
    (5432, "postgresql"),
    (5672, "rabbitmq"),
    (5900, "vnc"),
    (5901, "vnc"),
    (6379, "redis"),
    (7001, "weblogic"),
    (8000, "http"),
    (8008, "http"),
    (8080, "http"),
    (8443, "https"),
    (8888, "http"),
    (9000, "http"),
    (9001, "http"),
    (9090, "http"),
    (9200, "elasticsearch"),
    (9300, "elasticsearch"),
    (11211, "memcached"),
    (27017, "mongodb"),
    (50000, "http"),
]

PORT_SCAN_TIMEOUT = 0.8  # 单端口超时（秒）
PORT_SCAN_WORKERS = 20    # 并发线程数


def scan_port(host, port, timeout=PORT_SCAN_TIMEOUT):
    """尝试 TCP 连接，返回服务名或 None"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        result = s.connect_ex((host, port))
        s.close()
        if result == 0:
            # 找到对应服务名
            for p, svc in COMMON_PORTS:
                if p == port:
                    return svc
            return str(port)
    except Exception:
        pass
    return None


def scan_device_ports(host, timeout=PORT_SCAN_TIMEOUT, workers=PORT_SCAN_WORKERS):
    """扫描设备常见端口，返回 [(port, service), ...]"""
    open_ports = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(scan_port, host, port, timeout): port for port, _ in COMMON_PORTS}
        for future in as_completed(futures):
            svc = future.result()
            if svc:
                port = futures[future]
                open_ports.append((port, svc))
    # 按端口号排序
    open_ports.sort(key=lambda x: x[0])
    return open_ports


def _ping_subnet_fast(subnet_prefix, workers=30, timeout=0.5):
    """快速 ping 网段所有 IP，填充 ARP 缓存，返回可达 IP 列表"""
    def _ping1(ip):
        r = ping_once(ip, timeout=timeout)
        return ip if r is not None else None
    reached = []
    try:
        ips = [f"{subnet_prefix}.{i}" for i in range(1, 255)]
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
            future_to_ip = {ex.submit(_ping1, ip): ip for ip in ips}
            try:
                concurrent.futures.wait(future_to_ip.keys(), timeout=workers * timeout + 2)
            except Exception:
                pass
            for fut in future_to_ip:
                try:
                    res = fut.result(timeout=0)
                    if res:
                        reached.append(res)
                except Exception:
                    pass
        log.info("[拓扑] ping 扫描完成，%d/%d 台可达", len(reached), len(ips))
        if reached:
            log.info("[拓扑] 可达 IP: %s", ",".join(reached[:10]))
    except Exception as e:
        log.warning("[拓扑] ping 扫描异常: %s", e)
    return reached

def _get_mac_for_ip(ip):
    """用 getmac 或 arp -a 获取指定 IP 的 MAC 地址"""
    try:
        # 先尝试 getmac
        out, _ = _run_hidden(f'getmac /nh /fo csv /s {ip}', timeout=3)
        for line in out.splitlines():
            if ip in line or len(line) > 10:
                parts = line.split(",")
                if parts:
                    mac = parts[0].strip().strip('"').replace("-", ":").upper()
                    if len(mac) == 17 and mac.count(":") == 5:
                        return mac
        # 备用：arp -a 单 IP
        out2, _ = _run_hidden(f"arp -a {ip}", timeout=3)
        m = re.search(r"([0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}", out2)
        if m:
            return m.group(0).replace("-", ":").upper()
    except Exception:
        pass
    return ""

def get_all_devices_from_arp():
    """读取本机 ARP 缓存表，获取局域网已知设备（先 ping 填充 ARP 缓存）"""
    devices = []
    try:
        # 先快速 ping 网段填充 ARP 缓存
        subnet = get_subnet_prefix()
        log.info("[拓扑] 本机网段: %s", subnet)
        reached = []
        if subnet:
            log.info("[拓扑] 开始 ping 扫描...")
            reached = _ping_subnet_fast(subnet)
        else:
            log.warning("[拓扑] 无法获取本机网段，跳过 ping 扫描")
        # 解析 ARP 表
        ip_to_mac = {}
        if sys.platform == "win32":
            out, _ = _run_hidden('arp -a', timeout=5)
        else:
            out, _ = _run_hidden('arp -a -n', timeout=5)
        arp_lines = [l for l in out.splitlines() if l.strip()]
        log.info("[拓扑] ARP 表读取到 %d 行", len(arp_lines))
        for line in arp_lines:
            line = line.strip()
            m = re.search(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\s+([0-9a-fA-F:]{17})', line)
            if not m:
                m = re.search(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\s+([0-9a-fA-F]{2}[-:][0-9a-fA-F]{2}[:][0-9a-fA-F]{2}[:][0-9a-fA-F]{2}[:][0-9a-fA-F]{2}[:][0-9a-fA-F]{2})', line)
            if m:
                ip, mac = m.group(1), m.group(2).replace('-', ':').upper()
                if ip.endswith('.255') or mac.startswith('FF:FF'):
                    continue
                ip_to_mac[ip] = mac
        # ARP 表为空时，用 getmac 逐个获取可达 IP 的 MAC
        if not ip_to_mac and reached:
            log.info("[拓扑] ARP 表为空，尝试 getmac 获取 %d 个 IP 的 MAC", len(reached))
            for ip in reached[:20]:
                mac = _get_mac_for_ip(ip)
                if mac:
                    ip_to_mac[ip] = mac
                    log.debug("[拓扑] %s -> %s", ip, mac)
        # 生成设备列表
        for ip, mac in ip_to_mac.items():
            hostname = _resolve_hostname(ip) or ""
            vendor = get_vendor(mac)
            dtype = guess_device_type(hostname, vendor, mac)
            # 端口扫描（并发进行）
            open_ports = scan_device_ports(ip)
            port_strs = [f"{p}/{s}" for p, s in open_ports]
            if port_strs:
                log.debug("[端口] %s 发现 %s", ip, ",".join(port_strs))
            devices.append({"ip": ip, "mac": mac, "hostname": hostname, "vendor": vendor, "device_type": dtype, "open_ports": port_strs})
            log.debug("[拓扑] 发现 %s (%s) %s", ip, mac, vendor or "?")
    except Exception as e:
        log.warning("[拓扑] ARP 读取失败: %s", e)
    return devices


def scan_topology(subnets=None):
    """
    读取本机 ARP 缓存表获取局域网设备（不发包，静默扫描）
    仅在未配置 subnets 时自动检测本机所在网段的 ARP 条目
    """
    devices = get_all_devices_from_arp()
    log.info("[拓扑] ARP 扫描完成，发现 %d 台设备", len(devices))
    return devices


# ═══════════════════════════════════════════════════════════════
# 上报接口
# ═══════════════════════════════════════════════════════════════

def register_agent(company_name, phone="", location=""):
    """向服务端注册企业，返回 dict {agent_id, token, user_id, name} 或 None"""
    import socket
    # 强制设置全局 socket 超时，防止 urllib 挂死
    socket.setdefaulttimeout(5)
    try:
        data = json.dumps({
            "name": company_name,
            "phone": phone,
            "location": location,
            "remark": "lanwatch_agent_v0.7.0",
            "platform": "windows"
        }).encode()
        req = urllib.request.Request(
            SERVER_URL + "/api/register",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        log.info("[注册] 正在连接 %s...", SERVER_URL)
        with urllib.request.urlopen(req, timeout=5) as resp:
            result = json.loads(resp.read())
            log.info("[注册] 成功: agent_id=%s", result.get("agent_id"))
            return result
    except Exception as e:
        log.error("[注册] 失败: %s", e)
        import traceback
        log.error(traceback.format_exc())
        return None


def report(data, agent_id):
    """上报探测数据"""
    try:
        req = urllib.request.Request(
            SERVER_URL + "/api/" + agent_id + "/report",
            data=json.dumps(data).encode(),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as e:
        log.warning("上报失败: %s", e)
        return None


def report_offline(agent_id):
    """下线通知"""
    try:
        req = urllib.request.Request(
            SERVER_URL + "/api/" + agent_id + "/offline",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=5):
            pass
        log.info("[离线] 已通知服务端")
    except Exception:
        pass


def report_uninstall(agent_id, timeout=10):
    """卸载时通知服务端，标记该设备已卸载"""
    try:
        req = urllib.request.Request(
            SERVER_URL + "/api/" + agent_id + "/uninstall",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read())
            log.info("[卸载] 通知服务端成功: %s", result)
            return result
    except Exception as e:
        log.warning("[卸载] 通知服务端失败: %s", e)
        return None



# ═══════════════════════════════════════════════════════════════
# 离线断点诊断
# ═══════════════════════════════════════════════════════════════

TRACERT_TARGETS = ["www.baidu.com", "8.8.8.8"]
DIAG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "offline_diag.txt")


def run_traceroute(target):
    """执行 traceroute，返回跳列表或 None"""
    cmd = 'tracert -h 15 ' + target if sys.platform == "win32" else 'traceroute -m 15 ' + target
    try:
        out, _ = _run_hidden(cmd, timeout=30)
        hops = []
        for line in out.splitlines():
            m = re.search(r'^\s*(\d+)\s+.*?\s+([\d.]+)\s*ms', line)
            if m:
                hops.append({"hop": int(m.group(1)), "rtt": float(m.group(2))})
            elif '*' in line:
                hops.append({"hop": len(hops) + 1, "rtt": None})
        return hops if hops else None
    except Exception as e:
        log.warning("[诊断] traceroute 失败: %s", e)
        return None


def run_offline_diag():
    """执行离线诊断，保存本地文件"""
    log.warning("[诊断] 网络异常，开始离线断点诊断...")
    diag = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "target": None, "hops": None, "error": None}
    for target in TRACERT_TARGETS:
        hops = run_traceroute(target)
        if hops:
            diag["target"] = target
            diag["hops"] = hops
            break
    if not diag["target"]:
        diag["error"] = "所有目标均无法 traceroute"
    try:
        with open(DIAG_FILE, 'w', encoding='utf-8') as f:
            f.write("=== LanWatch 离线断点诊断 ===\n")
            f.write(f"时间: {diag['time']}\n")
            if diag["target"]:
                f.write(f"目标: {diag['target']}\n")
                f.write("跳数 | 延迟\n")
                for h in diag["hops"]:
                    rtt_str = f"{h['rtt']:.1f} ms" if h['rtt'] else "超时"
                    f.write(f"  {h['hop']:2d}   {rtt_str}\n")
            else:
                f.write(f"错误: {diag['error']}\n")
        log.info("[诊断] 诊断结果已保存: %s", DIAG_FILE)
    except Exception as e:
        log.error("[诊断] 写入诊断文件失败: %s", e)
    return diag


def report_diag(diag_data, agent_id):
    """上报诊断结果到服务端"""
    try:
        req = urllib.request.Request(
            SERVER_URL + "/api/" + agent_id + "/diag",
            data=json.dumps(diag_data).encode(),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            log.info("[诊断] 已上报服务端")
            return json.loads(resp.read())
    except Exception as e:
        log.warning("[诊断] 上报失败: %s", e)
        return None

def report_topology(devices, agent_id):
    """上报拓扑数据"""
    try:
        req = urllib.request.Request(
            SERVER_URL + "/api/" + agent_id + "/topology",
            data=json.dumps({"devices": devices}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as e:
        log.warning("拓扑上报失败: %s", e)
        return None


# ═══════════════════════════════════════════════════════════════
# 探测主函数
# ═══════════════════════════════════════════════════════════════

DEFAULT_TARGETS = None  # lazy init


def get_targets():
    global DEFAULT_TARGETS
    cfg = load_config()
    if cfg and cfg.get("targets"):
        return cfg["targets"]
    if DEFAULT_TARGETS is None:
        DEFAULT_TARGETS = [
            {"name": "网关", "host": get_gateway()},
            {"name": "DNS", "host": "8.8.8.8"},
        ]
    return DEFAULT_TARGETS


def run_probe(subnets=None):
    targets = get_targets()
    gateway = get_gateway()

    # 探测网关（3次 ICMP ping）
    gw_ok, gw_rtt, gw_loss = ping_multi(gateway, count=3, timeout=2)

    # DNS 延迟
    dns_ms = measure_dns_single("www.baidu.com")
    extra_dns = measure_dns_multi()

    # 探测目标列表（第一个可达的算目标）
    target_ok = False
    target_rtt = None
    target_name = ""
    for t in targets:
        rtt = ping_once(t["host"], timeout=3)
        if rtt is not None:
            target_ok = True
            target_rtt = rtt
            target_name = t["name"]
            break

    # 如果没配目标，默认把网关当目标
    if not target_name:
        target_ok = gw_ok
        target_rtt = gw_rtt
        target_name = "网关"

    return {
        "ping_ok": gw_ok,
        "ping_rtt_ms": gw_rtt,
        "ping_loss_pct": gw_loss,
        "dns_ms": dns_ms,
        "dns_ms_ali": extra_dns["dns_ali"],
        "dns_ms_tencent": extra_dns["dns_tencent"],
        "dns_ms_163": extra_dns["dns_163"],
        "gateway_reachable": gw_ok,
        "target_reachable": target_ok,
        "target_name": target_name,
        "target_rtt_ms": target_rtt,
        "subnets": ",".join(subnets) if subnets else "",
    }


# ═══════════════════════════════════════════════════════════════
# 托盘图标
# ═══════════════════════════════════════════════════════════════

def _create_tray_image(color_hex="#34c759"):
    """创建托盘图标（绿=在线，红=离线）"""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (16, 16), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([2, 2, 13, 13], fill=color_hex)
    return img


def setup_tray(agent_id, company_name):
    """初始化系统托盘，返回 icon 对象"""
    global _tray_icon_ref, _status_thread_started
    try:
        from pystray import Icon, MenuItem, Menu
        create_img = _create_tray_image

        def make_menu():
            return Menu(
                MenuItem("检查更新", lambda icon, item: _do_manual_upgrade_check(), default=False),
                MenuItem("查看日志", lambda icon, item: _open_log(), default=False),
                MenuItem("设置", lambda icon, item: _show_settings_window(), default=False),
                MenuItem("卸载", lambda icon, item: _on_uninstall(), default=False),
                MenuItem("关于", lambda icon, item: _show_about(), default=False),
                MenuItem("退出", lambda icon, item: _exit_app(), default=False),
            )

        icon = Icon(
            "lanwatch_agent",
            create_img("#34c759"),
            f"lanwatch ({company_name})",
            make_menu()
        )
        _tray_icon_ref = icon

        # 启动托盘状态轮询线程（只启动一次）
        global _status_thread_started
        if not _status_thread_started:
            t = threading.Thread(target=_poll_status_queue, daemon=True, name="tray_status")
            t.start()
            _status_thread_started = True

        def run_tray():
            icon.run()   # blocks until icon.stop() is called

        t = threading.Thread(target=run_tray, daemon=True, name="tray")
        t.start()
        log.info("[托盘] 启动成功")
        return icon
    except Exception as e:
        log.warning("[托盘] 启动失败: %s", e)
        return None


def update_tray_status(is_online):
    """线程安全地更新托盘状态（通过队列）"""
    try:
        _status_queue.put_nowait(("status", is_online))
    except Exception:
        pass


def _poll_status_queue():
    """在托盘线程中轮询状态队列，更新图标颜色"""
    global _tray_icon_ref
    current_color = None
    while True:
        try:
            op, data = _status_queue.get(timeout=1)
            if op == "status":
                color = "#34c759" if data else "#ff3b30"
                if color != current_color:
                    current_color = color
                    _do_update_tray_icon(color)
        except queue.Empty:
            continue
        except Exception as e:
            log.debug("[托盘] 状态轮询异常: %s", e)


def _do_update_tray_icon(color):
    """在托盘线程中安全更新图标和菜单文字（直接操作 pystray Icon 对象）"""
    global _tray_icon_ref
    try:
        if _tray_icon_ref is None:
            return
        # 更新图标图片
        _tray_icon_ref.icon = _create_tray_image(color)
        # 更新托盘提示文字
        _tray_icon_ref.title = f"lanwatch ({'在线' if color == '#34c759' else '离线'})"
        # pystray 菜单内容是每次右键点击时从 make_menu 动态读取的，
        # 图标本身更新后视觉上就会变化，不需要调用 update_menu()
        log.info("[托盘] 状态更新: %s", color)
    except Exception as e:
        log.warning("[托盘] 更新失败: %s", e)


def _poll_action_queue():
    """在 _tk_root 主循环中轮询动作队列，安全处理跨线程 UI 操作"""
    try:
        while True:
            try:
                op, data = _action_queue.get_nowait()
            except queue.Empty:
                break
            if op == "uninstall":
                _do_uninstall_confirm()
    except Exception:
        pass
    # 下次检查
    if _tk_root:
        _tk_root.after(200, _poll_action_queue)


def _do_uninstall_confirm():
    """显示卸载确认对话框（在主 Tk 线程中调用）"""
    from tkinter import messagebox
    # 明确指定 parent，避免 messagebox 内部创建新的 Tk 嵌套 mainloop 导致卡死
    if not messagebox.askyesno("卸载确认",
                               "确定要卸载 lanwatch 吗？\n\n将删除所有配置并停止监控。",
                               parent=_tk_root):
        return
    log.info("[卸载] 开始卸载...")
    config = load_config()
    agent_id = config.get("agent_id") if config else None

    # 1. 删除自启动
    set_autostart(False)
    log.info("[卸载] 自启已删除")

    # 2. 同步通知服务端（卸载时不能用 daemon 线程 + os._exit，否则线程会来不及发出请求）
    if agent_id:
        log.info("[卸载] 正在通知服务端...")
        report_uninstall(agent_id, timeout=3)

    # 3. 删除配置文件
    try:
        if os.path.exists(CONFIG_FILE):
            os.remove(CONFIG_FILE)
            log.info("[卸载] 配置已删除")
    except Exception as e:
        log.error("[卸载] 删除配置失败: %s", e)

    # 4. 关进程
    log.info("[卸载] 完成")
    os._exit(0)


def _open_log(icon=None):
    """打开日志文件"""
    try:
        os.startfile(LOG_FILE) if sys.platform == "win32" else None
    except Exception:
        pass


def _show_about(icon=None):
    """显示关于对话框"""
    from tkinter import Toplevel, Label, Button, messagebox
    try:
        win = Toplevel(_tk_root)
        win.title("关于 lanwatch_agent")
        win.geometry("320x180")
        win.resizable(False, False)
        win.attributes("-topmost", True)
        win.update_idletasks()
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        ww, wh = 320, 180
        win.geometry(f"{ww}x{wh}+{(sw-ww)//2}+{(sh-wh)//2}")

        Label(win, text=f"lanwatch_agent v{__version__}", font=("Arial", 12, "bold")).place(x=20, y=20)
        Label(win, text="企业网络监控客户端", font=("Arial", 10)).place(x=20, y=50)
        Label(win, text=f"服务端: {SERVER_URL}", font=("Arial", 9), fg="#666").place(x=20, y=75)

        def do_check():
            check_and_upgrade()

        Button(win, text="检查更新", command=do_check, width=12).place(x=20, y=115)
        Button(win, text="关闭", command=win.destroy, width=12).place(x=165, y=115)

        win.protocol("WM_DELETE_WINDOW", win.destroy)
    except Exception:
        pass


def _exit_app(icon=None):
    """安全退出（通知服务端后退出）"""
    global _tray_icon_ref
    log.info("[托盘] 请求退出")
    config = load_config()
    if config and config.get("agent_id"):
        report_offline(config["agent_id"])
    if _tray_icon_ref:
        try:
            _tray_icon_ref.stop()
        except Exception:
            pass
    os._exit(0)


def _on_uninstall():
    """卸载：放入队列，由主 Tk 线程处理，避免跨线程卡死"""
    _action_queue.put(("uninstall", None))


def _show_settings_window():
    """显示设置窗口（托盘点击"设置"触发）：自启动开关"""
    try:
        from tkinter import Toplevel, Label, Checkbutton, IntVar, messagebox, Button, Frame
        cfg = load_config()
        win = Toplevel(_tk_root)
        win.title("设置")
        win.geometry("340x220")
        win.resizable(False, False)
        win.attributes("-topmost", True)
        win.update_idletasks()
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        ww, wh = 340, 220
        win.geometry(f"{ww}x{wh}+{(sw-ww)//2}+{(sh-wh)//2}")

        # 标题
        Label(win, text="lanwatch_agent v" + __version__, font=("微软雅黑", 10, "bold")).place(x=20, y=16)
        Label(win, text="企业网络监控客户端", font=("微软雅黑", 9), fg="#666").place(x=20, y=42)

        # 自启动开关（不立即生效，等点确定）
        auto_var = IntVar(value=1 if is_autostart_enabled() else 0)
        cb = Checkbutton(
            win, text="开机自启动",
            variable=auto_var,
            font=("微软雅黑", 10),
            onvalue=1, offvalue=0
        )
        cb.place(x=20, y=78)

        # 服务器地址（只读）
        Label(win, text="服务端: " + SERVER_URL, font=("微软雅黑", 8), fg="#888").place(x=20, y=130)

        # 按钮栏
        btn_frame = Frame(win)
        btn_frame.pack(side="bottom", fill="x", padx=20, pady=(0, 16))

        def on_ok():
            ok = set_autostart(bool(auto_var.get()))
            if ok:
                status = "已开启" if auto_var.get() else "已关闭"
                log.info("[设置] 自启动: %s", status)
            else:
                messagebox.showwarning("设置失败", "无法修改自启动设置", parent=win)
                return
            win.destroy()

        def on_cancel():
            win.destroy()

        ok_btn = Button(btn_frame, text="确定", font=("微软雅黑", 9), command=on_ok,
                        bg="#2563EB", fg="white", relief="flat", pady=5)
        ok_btn.pack(side="left", fill="x", expand=True, padx=(0, 8))

        cancel_btn = Button(btn_frame, text="取消", font=("微软雅黑", 9), command=on_cancel,
                            bg="#F3F4F6", fg="#374151", relief="flat", pady=5)
        cancel_btn.pack(side="left", fill="x", expand=True)

        win.protocol("WM_DELETE_WINDOW", on_cancel)
    except Exception as e:
        log.warning("[设置] 窗口打开失败: %s", e)
        _show_about()


# ═══════════════════════════════════════════════════════════════
# 开机自启
# ═══════════════════════════════════════════════════════════════

def set_autostart(enable=True):
    if not _winreg:
        return False
    try:
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        key = _winreg.OpenKey(_winreg.HKEY_CURRENT_USER, key_path, 0, _winreg.KEY_ALL_ACCESS)
        if enable:
            if getattr(sys, "frozen", False):
                # PyInstaller 打包后直接运行 exe
                cmd = f'"{sys.executable}"'
            else:
                exe_path = sys.executable
                # python.exe → pythonw.exe（无窗口）
                if exe_path.lower().endswith("python.exe"):
                    pythonw = exe_path[:-10] + "pythonw.exe"
                    if os.path.exists(pythonw):
                        exe_path = pythonw
                script_path = os.path.abspath(__file__)
                cmd = f'"{exe_path}" "{script_path}"'
            _winreg.SetValueEx(key, "lanwatch_agent", 0, _winreg.REG_SZ, cmd)
            log.info("[自启] 已开启: %s", cmd)
        else:
            try:
                _winreg.DeleteValue(key, "lanwatch_agent")
                log.info("[自启] 已关闭")
            except FileNotFoundError:
                pass
        _winreg.CloseKey(key)
        return True
    except Exception as e:
        log.warning("[自启] 设置失败: %s", e)
        return False


def is_autostart_enabled():
    if not _winreg:
        return False
    try:
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        key = _winreg.OpenKey(_winreg.HKEY_CURRENT_USER, key_path, 0, _winreg.KEY_READ)
        try:
            val, _ = _winreg.QueryValueEx(key, "lanwatch_agent")
            _winreg.CloseKey(key)
            return bool(val)
        except FileNotFoundError:
            _winreg.CloseKey(key)
            return False
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════
# GUI 窗口（设置向导 + 成功提示）
# ═══════════════════════════════════════════════════════════════

def _show_setup_window(root):
    """极简设置向导（modeless，不阻塞）"""
    import tkinter as tk
    from tkinter import messagebox
    from threading import Thread

    result = {}
    win = tk.Toplevel(root)
    win.title("lanwatch - 首次设置")
    W, H = 440, 560
    win.geometry(f"{W}x{H}")
    win.resizable(False, False)
    win.attributes("-topmost", True)
    win.update_idletasks()
    sw = root.winfo_screenwidth(); sh = root.winfo_screenheight()
    win.geometry(f"+{(sw-W)//2}+{(sh-H)//2}")
    win.protocol("WM_DELETE_WINDOW", lambda: None)  # 禁止点X

    BG="#FFFFFF"; ACCENT="#2563EB"; TEXT="#111827"; TEXT2="#6B7280"
    GREEN="#10B981"; INPUT_BG="#F9FAFB"
    win.configure(bg=BG)

    # 顶部
    header = tk.Frame(win, bg="#F3F4F6")
    header.pack(fill="x")
    tk.Label(header, text="◉ lanwatch", font=("微软雅黑",14,"bold"),
             bg="#F3F4F6", fg=ACCENT).pack(pady=(12,1))
    tk.Label(header, text="首次设置向导", font=("微软雅黑",9),
             bg="#F3F4F6", fg=TEXT2).pack(pady=(0,10))

    # 表单
    form = tk.Frame(win, bg=BG)
    form.pack(fill="x", padx=36, pady=(8,0))

    def entry(parent):
        e = tk.Entry(parent, font=("微软雅黑",10), bg=INPUT_BG, fg=TEXT,
                     insertbackground=ACCENT, relief="solid", bd=1,
                     highlightthickness=0)
        e.pack_configure(pady=(3,8), ipady=5, padx=0)
        return e

    def label_row(parent, text):
        tk.Label(parent, text=text, font=("微软雅黑",9,"bold"),
                 bg=BG, fg=TEXT2).pack(anchor="w", pady=(6,1))

    label_row(form, "企业名称 *")
    name_entry = entry(form); name_entry.pack(fill="x")

    label_row(form, "安装地址")
    addr_entry = entry(form); addr_entry.pack(fill="x")

    label_row(form, "网关电话（选填）")
    phone_entry = entry(form); phone_entry.pack(fill="x")

    status_lbl = tk.Label(form, text="", font=("微软雅黑", 9), bg=BG, fg=TEXT2, anchor="w")
    status_lbl.pack(fill="x", pady=(4,0))

    # 开机自启
    autostart_var = tk.BooleanVar(value=True)
    tk.Checkbutton(form, text="开机自动启动", variable=autostart_var,
                   font=("微软雅黑", 10), bg=BG, fg=TEXT,
                   activebackground=BG, anchor="w", pady=8).pack(anchor="w")


    # 按钮行
    btn_frame = tk.Frame(win, bg=BG)
    btn_frame.pack(side="bottom", fill="x", padx=36, pady=14)

    def on_ok():
        name = name_entry.get().strip()
        if not name:
            messagebox.showwarning("提示","请填写企业名称", parent=win); return
        company_name = name
        phone        = phone_entry.get().strip()
        location     = addr_entry.get().strip()
        subnet       = get_subnet_prefix() or ""

        # 显示进度状态
        for w in btn_frame.winfo_children():
            try: w.config(state="disabled")
            except Exception: pass
        status_lbl.config(text="正在注册...", fg=TEXT2)
        win.update_idletasks()

        def _do_register():
            try:
                reg = register_agent(company_name, phone, location)
                if not reg:
                    root.after(0, lambda: status_lbl.config(text="注册失败", fg="#EF4444"))
                    root.after(0, lambda: [w.config(state="normal") for w in btn_frame.winfo_children()])
                    root.after(0, lambda: _show_err("注册失败，请检查网络后重试。"))
                    return
                agent_id = reg["agent_id"]
                token    = reg["token"]
                log.info("注册成功，Agent ID: %s", agent_id)
                cfg = {
                    "agent_id": agent_id, "company_name": company_name,
                    "phone": phone, "location": location,
                    "subnets": [subnet] if subnet and subnet != "无法检测" else [],
                    "targets": [{"name": "网关", "host": get_gateway()}],
                }
                save_config(cfg)
                # 设置开机自启（根据用户选择）
                if autostart_var.get():
                    set_autostart(True)
                win.after(0, lambda: _show_success_window(root, win, company_name, agent_id, token))
            except Exception as e:
                import traceback
                log.error("注册异常: %s", e)
                log.error(traceback.format_exc())
                win.after(0, lambda msg=str(e): [
                    status_lbl.config(text="异常: %s" % msg[:50], fg="#EF4444"),
                    [w.config(state="normal") for w in btn_frame.winfo_children()]
                ])
                win.after(0, lambda: _show_err("注册异常: %s" % e))

        def _show_err(msg):
            def _show():
                from tkinter import messagebox
                messagebox.showerror("注册异常", msg)
            try:
                root.after(0, _show)
            except Exception:
                log.error("无法显示错误弹窗: %s", msg)

        threading.Thread(target=_do_register, daemon=True, name="register").start()

    def on_cancel():
        result["cancelled"] = True
        win.destroy()
        root.quit()

    # 状态标签（显示注册进度）
    status_lbl = tk.Label(form, text="", font=("微软雅黑", 9), bg=BG, fg=TEXT2, anchor="w")
    status_lbl.pack(fill="x", pady=(4,0))

    tk.Button(btn_frame, text="取消", command=on_cancel,
             font=("微软雅黑",10), width=10, bg="#F3F4F6", fg=TEXT2,
             relief="flat", pady=7).pack(side="left")
    tk.Button(btn_frame, text="确认注册", command=on_ok,
             font=("微软雅黑",10,"bold"), width=10, bg=ACCENT, fg="white",
             relief="flat", pady=7).pack(side="right")

    # 不阻塞，窗口关闭后自动清理
    def _cleanup():
        pass
    return (
        result.get("company_name",""),
        result.get("phone",""),
        result.get("location",""),
        result.get("subnet",""),
        result.get("cancelled",True),
    )



def _show_success_window(root, setup_win, company_name, agent_id, token):
    """注册成功窗口"""
    import tkinter as tk
    from PIL import Image, ImageTk
    import io as _io

    win = tk.Toplevel(root)
    win.title("注册成功 - lanwatch")
    W, H = 400, 520
    win.geometry(f"{W}x{H}")
    win.resizable(False, False)
    win.attributes("-topmost", True)
    win.update_idletasks()
    sw = root.winfo_screenwidth(); sh = root.winfo_screenheight()
    win.geometry(f"+{(sw-W)//2}+{(sh-H)//2}")

    BG="#FFFFFF"; ACCENT="#2563EB"; TEXT="#111827"; TEXT2="#6B7280"
    GREEN="#10B981"; INPUT_BG="#F9FAFB"
    win.configure(bg=BG)

    header = tk.Frame(win, bg="#F3F4F6")
    header.pack(fill="x")
    tk.Label(header, text="✓  注册成功", font=("微软雅黑",15,"bold"),
             bg="#F3F4F6", fg=GREEN).pack(pady=(14,2))
    tk.Label(header, text=company_name, font=("微软雅黑",10),
             bg="#F3F4F6", fg=TEXT2).pack(pady=(0,12))

    main = tk.Frame(win, bg=BG)
    main.pack(fill="both", expand=True, padx=32, pady=(12,0))

    qr_label = tk.Label(main, bg=BG, text=" ", width=20, height=12)
    qr_label.pack()
    loading_lbl = tk.Label(main, text="正在加载二维码...", font=("微软雅黑",9),
                           bg=BG, fg=TEXT2)
    loading_lbl.pack(pady=(4,0))
    qr_label._ref = qr_label
    loading_lbl._ref = loading_lbl

    def load_qr():
        try:
            import urllib.request
            req = urllib.request.Request(
                SERVER_URL + f"/api/agents/{agent_id}/qr",
                headers={"User-Agent": "lanwatch_agent"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                img_bytes = resp.read()
            buf = _io.BytesIO(img_bytes)
            img = Image.open(buf)
            img = img.resize((180, 180))
            photo = ImageTk.PhotoImage(img)
            qr_label.config(image=photo, text="")
            qr_label.image = photo
            loading_lbl.config(text="手机扫码查看监控 · " + agent_id)
        except Exception as e:
            try:
                loading_lbl.config(text="二维码加载失败", fg="#EF4444")
            except Exception:
                pass

    threading.Thread(target=load_qr, daemon=True).start()

    tk.Label(main, text="Agent ID: " + agent_id, font=("微软雅黑",9),
             bg=BG, fg=TEXT2).pack(pady=(8,0))

    token_frame = tk.Frame(main, bg=INPUT_BG, relief="solid", bd=1,
                           highlightbackground="#D1D5DB")
    token_frame.pack(fill="x", pady=(10,0))
    tk.Label(token_frame, text="Token（请妥善保存，遗失无法找回）",
             font=("微软雅黑",8), bg=INPUT_BG, fg=TEXT2).pack(
                 anchor="w", padx=10, pady=(6,0))
    tk.Label(token_frame, text=token, font=("Consolas",9),
             bg=INPUT_BG, fg=ACCENT).pack(anchor="w", padx=10, pady=(0,8))

    btn_frame = tk.Frame(win, bg=BG)
    btn_frame.pack(side="bottom", fill="x", padx=32, pady=14)

    tk.Button(btn_frame, text="打开监控页面",
             command=lambda: _open_mobile(agent_id),
             font=("微软雅黑",9), bg=ACCENT, fg="white",
             relief="flat", pady=7).pack(side="left", fill="x", expand=True, padx=(0,4))
    tk.Button(btn_frame, text="复制 Token",
             command=lambda: _copy_token(root, token),
             font=("微软雅黑",9), bg="#F3F4F6", fg=TEXT,
             relief="flat", pady=7).pack(side="left", fill="x", expand=True, padx=4)
    tk.Button(btn_frame, text="完 成",
             command=lambda: _dismiss_and_start(win, setup_win, root, agent_id, company_name),
             font=("微软雅黑",9,"bold"), bg=GREEN, fg="white",
             relief="flat", pady=7).pack(side="left", fill="x", expand=True, padx=(4,0))

    win.protocol("WM_DELETE_WINDOW", lambda: _dismiss_and_start(win, setup_win, root, agent_id, company_name))
    win.wait_window()


def _dismiss_and_start(success_win, setup_win, root, agent_id, company_name):
    """关闭注册成功窗口（如有），关闭 setup 向导，退出 Tk 主循环"""
    success_win.destroy()
    if setup_win is not None:
        setup_win.destroy()  # 关闭 setup 向导，让其 wait_window() 返回
    root.quit()  # 退出 main() 的 root.mainloop()


def _open_mobile(agent_id):
    import webbrowser
    webbrowser.open(f"http://82.156.229.67:8000/mobile?agent={agent_id}")


def _copy_token(root, token):
    root.clipboard_clear()
    root.clipboard_append(token)
    for w in root.winfo_children():
        if isinstance(w, tk.Button) and "复制" in str(w.cget("text")):
            w.config(text="已复制!", bg="#10b981")


def main():
    global _winreg, _tray_icon_ref, _tk_root

    import tkinter as tk
    _tk_root = tk.Tk()
    _tk_root.withdraw()  # 隐藏根窗口，用于跨线程安全调用
    root = _tk_root

    log.info("=" * 50)
    log.info("lanwatch_agent v%s 启动", __version__)
    log.info("服务端: %s", SERVER_URL)
    log.info("=" * 50)

    # Windows: 隐藏控制台窗口
    if sys.platform == "win32":
        try:
            ctypes.windll.user32.ShowWindow(
                ctypes.windll.kernel32.GetConsoleWindow(), 0
            )
        except Exception:
            pass
        _winreg = __import__("winreg")

    config = load_config()

    # ── 首次注册 ──
    if not config or not config.get("agent_id"):
        log.info("首次运行，显示设置向导...")
        _show_setup_window(root)
        # 启动 Tk 事件循环，保持程序运行
        # 点"完成"后 root.quit() 退出此循环
        root.mainloop()
        # 检查是否完成注册
        cfg2 = load_config()
        if not cfg2 or not cfg2.get("agent_id"):
            log.warning("注册未完成，退出")
            return
        agent_id = cfg2["agent_id"]
        company_name = cfg2.get("company_name", "")
    else:
        agent_id = config["agent_id"]
        company_name = config.get("company_name", "")
        log.info("已配置 Agent ID: %s", agent_id)

    # 托盘（已注册用户也启动托盘）
    if _tray_icon_ref is None:
        tray_icon = setup_tray(agent_id, company_name)
    else:
        tray_icon = _tray_icon_ref

    # 启动 action 队列轮询（在 Tk 主线程中）
    _tk_root.after(200, _poll_action_queue)

    # 监控主循环放在独立线程，避免阻塞 Tk mainloop
    def run_monitor():
        _run_monitoring(agent_id, company_name)
    threading.Thread(target=run_monitor, daemon=True, name="monitor").start()

    # 运行 Tk 主循环，处理 after() 回调和 action 队列
    _tk_root.mainloop()
    log.info("Agent 已停止")

def _run_monitoring(agent_id, company_name):
    """监控主循环"""
    global consecutive_errors
    log.info("开始监控探测...")
    consecutive_errors = 0
    topo_next_in = TOPOLOGY_INTERVAL
    upgrade_next_in = UPDATE_CHECK_INTERVAL  # 首次启动先等一会儿再检查
    while True:
        try:
            cfg = load_config()
            subnets = (cfg or {}).get("subnets", [])
            targets = (cfg or {}).get("targets", DEFAULT_TARGETS)
            data = run_probe(subnets)
            result = report(data, agent_id)
            if result:
                consecutive_errors = 0
                update_tray_status(data.get("dns_ms") is not None)
                log.info("[探测] 网关:%sms DNS:%sms",
                    f"{data.get('ping_rtt_ms', 0):.1f}" if data.get('ping_rtt_ms') else "-",
                    f"{data.get('dns_ms', 0):.1f}" if data.get('dns_ms') else "-")
            else:
                consecutive_errors += 1
                log.warning("[探测] 上报失败 (连续失败 %d 次)", consecutive_errors)
                if consecutive_errors >= 3:
                    diag = run_offline_diag()
                    threading.Thread(target=lambda: report_diag(diag, agent_id), daemon=True, name="diag").start()
                update_tray_status(False)
        except KeyboardInterrupt:
            log.info("收到停止信号")
            break
        except Exception as e:
            log.error("[探测] 运行异常: %s", e)
            consecutive_errors += 1
            update_tray_status(False)

        topo_next_in -= REPORT_INTERVAL
        if topo_next_in <= 0:
            topo_next_in = TOPOLOGY_INTERVAL
            threading.Thread(target=_do_topology_scan,
                           args=((cfg or {}).get("subnets", []), agent_id),
                           daemon=True, name="topology").start()
        upgrade_next_in -= REPORT_INTERVAL
        if upgrade_next_in <= 0:
            upgrade_next_in = UPDATE_CHECK_INTERVAL
            threading.Thread(target=check_and_upgrade, daemon=True, name="upgrade_check").start()
        sleep(REPORT_INTERVAL)

    report_offline(agent_id)
    global _tray_icon_ref
    if _tray_icon_ref:
        try: _tray_icon_ref.stop()
        except Exception: pass
    log.info("监控已停止")



def _do_topology_scan(subnets, agent_id):
    """执行拓扑扫描并上报（后台线程调用）"""
    try:
        devices = scan_topology(subnets) if subnets else scan_topology()
        if devices:
            report_topology(devices, agent_id)
    except Exception as e:
        log.error("[拓扑] 扫描异常: %s", e)


if __name__ == "__main__":
    main()
