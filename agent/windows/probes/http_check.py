"""HTTP 健康检查模块"""
import httpx, time
from typing import Dict


def check_url(url: str, timeout: float = 5.0) -> Dict:
    start = time.time()
    try:
        r = httpx.get(url, timeout=timeout, follow_redirects=True,
                      headers={"User-Agent": "LanwatchAgent/1.0"})
        rtt = (time.time() - start) * 1000
        return {"url": url, "status_code": r.status_code, "response_time_ms": round(rtt, 2), "reachable": True, "error": None}
    except httpx.TimeoutException:
        return {"url": url, "status_code": None, "response_time_ms": None, "reachable": False, "error": "超时"}
    except Exception as e:
        return {"url": url, "status_code": None, "response_time_ms": None, "reachable": False, "error": str(e)}
