import socket, random, time, platform
from typing import List, Tuple, Optional


def traceroute(target: str, max_hops: int = 30, timeout: float = 3.0, port: int = 33434) -> List[dict]:
    """
    实现 UDP-based traceroute。
    适用于 Linux/macOS，Windows 可调用系统 tracert。
    返回: [{"ttl": 1, "ip": "192.168.1.1", "rtt_ms": 1.2}, ...]
    超时的 hop 返回 ip="", rtt_ms=None
    """
    results = []
    is_windows = platform.system().lower() == "windows"

    if is_windows:
        return _traceroute_windows(target, max_hops, timeout)
    else:
        return _traceroute_linux(target, max_hops, timeout, port)


def _traceroute_linux(target: str, max_hops: int, timeout: float, port: int) -> List[dict]:
    results = []
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


def _traceroute_windows(target: str, max_hops: int, timeout: float) -> List[dict]:
    import subprocess, re
    results = []
    try:
        output = subprocess.check_output(["tracert", "-h", str(max_hops), "-w", str(int(timeout * 1000)), target],
                                        stderr=subprocess.DEVNULL, timeout=timeout * max_hops + 10)
        lines = output.decode(errors="ignore").split("\n")
        for line in lines:
            m = re.match(r"\s*(\d+)\s+(?:(\S+)\s+|<(\d+)\s+ms\s+)(\d+\s*ms|\s+)?", line)
            if m:
                ttl = int(m.group(1))
                ip = m.group(2) if m.group(2) else ""
                rtt = None
                if m.group(3):
                    rtt = float(m.group(3))
                elif m.group(4):
                    rm = re.search(r"(\d+)\s*ms", m.group(4))
                    if rm:
                        rtt = float(rm.group(1))
                results.append({"ttl": ttl, "ip": ip, "rtt_ms": rtt})
    except Exception:
        pass
    return results
