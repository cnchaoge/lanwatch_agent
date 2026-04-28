"""traceroute 探测模块"""
import subprocess, platform, re, socket, random, time
from typing import List, Dict


def traceroute(target: str, max_hops: int = 30, timeout: int = 5) -> List[Dict]:
    """
    执行 traceroute。
    Windows 用系统 tracert，Linux/macOS 用 UDP-based traceroute。
    返回: [{"ttl": 1, "ip": "192.168.1.1", "rtt_ms": 1.2}, ...]
    """
    is_windows = platform.system().lower() == "windows"

    if is_windows:
        return _traceroute_windows(target, max_hops, timeout)
    else:
        return _traceroute_unix(target, max_hops, timeout)


def _traceroute_unix(target: str, max_hops: int, timeout: int) -> List[Dict]:
    """UDP-based traceroute for Linux/macOS"""
    results = []
    port = 33434
    for ttl in range(1, max_hops + 1):
        addr = ("", 0)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_IP, socket.IP_TTL, ttl)
        sock.settimeout(timeout)
        try:
            send_time = time.time()
            sock.sendto(b"lanwatch", (target, port + ttl))
            try:
                data, addr = sock.recvfrom(512)
                rtt = (time.time() - send_time) * 1000
                results.append({"ttl": ttl, "ip": addr[0], "rtt_ms": round(rtt, 2)})
            except socket.timeout:
                results.append({"ttl": ttl, "ip": "", "rtt_ms": None})
        except OSError:
            results.append({"ttl": ttl, "ip": "", "rtt_ms": None})
        finally:
            sock.close()
        if addr[0] == target:
            break
    return results


def _traceroute_windows(target: str, max_hops: int, timeout: int) -> List[Dict]:
    """Windows system tracert"""
    results = []
    try:
        output = subprocess.check_output(
            ["tracert", "-h", str(max_hops), "-w", str(timeout * 1000), target],
            stderr=subprocess.DEVNULL,
            timeout=timeout * max_hops + 10
        )
        lines = output.decode(errors="ignore").split("\n")
        for line in lines:
            m = re.match(r"\s*(\d+)\s+(?:(\S+)\s+|<(\d+)\s+ms\s+)(\d+\s*ms|\s+)?", line)
            if m:
                ttl = int(m.group(1))
                ip = m.group(2) if m.group(2) else ""
                rtt = None
                if m.group(3):
                    try:
                        rtt = float(m.group(3))
                    except Exception:
                        pass
                results.append({"ttl": ttl, "ip": ip, "rtt_ms": rtt})
    except Exception:
        pass
    return results
