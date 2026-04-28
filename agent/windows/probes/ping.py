"""
ping 探测模块：
- 从原有 lanwatch_agent.py 的 ping 逻辑迁移
- 新增 ping_results() 生成探测报告
"""
import subprocess, re, platform, time
from typing import List, Dict, Optional


def ping_once(host: str, timeout: int = 4) -> tuple:
    """单次 ping，返回 (成功, 延迟ms)"""
    is_windows = platform.system().lower() == "windows"
    param = "-n" if is_windows else "-c"
    timeout_flag = "-w" if is_windows else "-W"
    timeout_val = str(timeout * 1000) if not is_windows and platform.system().lower() == "darwin" else str(timeout)
    if is_windows:
        timeout_val = str(timeout * 1000)
    cmd = ["ping", param, "1", timeout_flag, timeout_val, host]
    try:
        output = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=timeout + 2)
        text = output.decode(errors="ignore")
        match = re.search(r"time[=<]\s*(\d+\.?\d*)\s*ms", text, re.IGNORECASE)
        if match:
            return True, float(match.group(1))
        if "TTL=" in text.upper():
            return True, 0.0
        return True, 0.0
    except Exception:
        return False, None


def ping_host(host: str, count: int = 4, timeout: int = 4) -> Dict:
    """执行多次 ping，返回汇总结果"""
    received, rtts = 0, []
    for _ in range(count):
        ok, rtt = ping_once(host, timeout)
        if ok:
            received += 1
            if rtt is not None:
                rtts.append(rtt)
    loss = (count - received) / count if count > 0 else 1.0
    return {
        "host": host, "sent": count, "received": received, "loss_rate": round(loss, 3),
        "avg_rtt_ms": round(sum(rtts)/len(rtts), 2) if rtts else None,
        "min_rtt_ms": round(min(rtts), 2) if rtts else None,
        "max_rtt_ms": round(max(rtts), 2) if rtts else None,
        "status": "unreachable" if received == 0 else "degraded" if loss > 0.2 else "ok"
    }


def ping_targets(targets: List[str], count: int = 2) -> List[Dict]:
    """对多个目标执行 ping，返回探测结果列表"""
    results = []
    for target in targets:
        r = ping_host(target, count=count)
        results.append(r)
    return results


def ping_results(targets: List[str] = None) -> List[Dict]:
    """
    生成探测报告列表（供主循环上报使用）。
    默认探测网关和几个常用外网 IP。
    """
    if targets is None:
        targets = _get_default_targets()
    reports = []
    for target in targets:
        r = ping_host(target, count=2)
        reports.append({
            "probe_type": "ping",
            "target": target,
            "status": r["status"],
            "rtt_ms": r["avg_rtt_ms"],
            "output": r
        })
    return reports


def _get_default_targets() -> List[str]:
    """获取默认探测目标"""
    targets = []
    gw = _get_gateway()
    if gw:
        targets.append(gw)
    targets.extend(["8.8.8.8", "114.114.114.114"])
    return targets


def _get_gateway() -> Optional[str]:
    """获取本机默认网关"""
    try:
        if platform.system().lower() == "windows":
            output = subprocess.check_output("route print 0.0.0.0", stderr=subprocess.DEVNULL)
            lines = output.decode(errors="ignore").split("\n")
            for line in lines:
                if "0.0.0.0" in line and not line.strip().startswith("0.0.0.0"):
                    parts = line.split()
                    if len(parts) >= 3:
                        return parts[2]
        else:
            output = subprocess.check_output("ip route | grep default", stderr=subprocess.DEVNULL)
            parts = output.decode().split()
            if "via" in parts:
                idx = parts.index("via")
                return parts[idx + 1] if idx + 1 < len(parts) else None
    except Exception:
        pass
    return None
