import socket, time, concurrent.futures
from typing import List, Dict

COMMON_PORTS = {
    21: "FTP", 22: "SSH", 23: "Telnet", 25: "SMTP", 53: "DNS",
    80: "HTTP", 110: "POP3", 143: "IMAP", 443: "HTTPS",
    445: "SMB", 3306: "MySQL", 3389: "RDP", 5432: "PostgreSQL",
    6379: "Redis", 8080: "HTTP-Alt", 8443: "HTTPS-Alt", 27017: "MongoDB"
}


def check_port(host: str, port: int, timeout: float = 3.0) -> Dict:
    """检测单个端口，返回 {"port": int, "status": "open"/"closed"/"filtered", "rtt_ms": float}"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    start = time.time()
    try:
        result = sock.connect_ex((host, port))
        rtt = (time.time() - start) * 1000
        if result == 0:
            return {"port": port, "status": "open", "rtt_ms": round(rtt, 2)}
        else:
            return {"port": port, "status": "closed", "rtt_ms": round(rtt, 2)}
    except socket.timeout:
        return {"port": port, "status": "filtered", "rtt_ms": None}
    except socket.error:
        return {"port": port, "status": "filtered", "rtt_ms": None}
    finally:
        sock.close()


def scan_ports(host: str, ports: List[int] = None, concurrency: int = 50) -> Dict[int, Dict]:
    """并发扫描多个端口"""
    if ports is None:
        ports = list(COMMON_PORTS.keys())
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {executor.submit(check_port, host, p): p for p in ports}
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            results[result["port"]] = {"status": result["status"], "rtt_ms": result["rtt_ms"]}
    return results


def scan_common_ports(host: str, concurrency: int = 50) -> Dict[int, Dict]:
    """扫描常用端口"""
    return scan_ports(host, list(COMMON_PORTS.keys()), concurrency)
