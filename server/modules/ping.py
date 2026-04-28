import re, subprocess, platform
from typing import Tuple, Optional


def ping_once(host: str, timeout: int = 4) -> Tuple[bool, Optional[float]]:
    param = "-n" if platform.system().lower() == "windows" else "-c"
    is_macos = platform.system().lower() == "darwin"
    # macOS -W is milliseconds, Linux -W is seconds
    timeout_arg = str(timeout * 1000) if is_macos else str(timeout)
    cmd = ["ping", param, "1", "-W", timeout_arg, host]
    try:
        output = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=timeout + 1)
        output_str = output.decode(errors="ignore")
        match = re.search(r"time[=<]\s*(\d+\.?\d*)\s*ms", output_str, re.IGNORECASE)
        if match:
            return True, float(match.group(1))
        return True, None
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, OSError):
        return False, None


def ping_host(host: str, count: int = 4, timeout: int = 4) -> dict:
    received, rtts = 0, []
    for _ in range(count):
        ok, rtt = ping_once(host, timeout)
        if ok:
            received += 1
            if rtt is not None:
                rtts.append(rtt)
    loss_rate = (count - received) / count if count > 0 else 1.0
    return {
        "host": host, "sent": count, "received": received, "loss_rate": round(loss_rate, 3),
        "avg_rtt_ms": round(sum(rtts)/len(rtts), 2) if rtts else None,
        "min_rtt_ms": round(min(rtts), 2) if rtts else None,
        "max_rtt_ms": round(max(rtts), 2) if rtts else None,
        "status": "unreachable" if received == 0 else "degraded" if loss_rate > 0.2 else "ok"
    }
