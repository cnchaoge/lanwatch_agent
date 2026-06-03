import httpx, time
import logging
logger = logging.getLogger("http_check")
from typing import Dict, Optional


def check_url(url: str, timeout: float = 5.0, follow_redirects: bool = True) -> Dict:
    """
    HTTP/HTTPS 健康检查。
    返回: {
        "url": str,
        "status_code": int,
        "response_time_ms": float,
        "reachable": bool,
        "error": Optional[str],
        "title": Optional[str]   # 从 <title> 标签提取
    }
    """
    start = time.time()
    try:
        response = httpx.get(url, timeout=timeout, follow_redirects=follow_redirects,
                             headers={"User-Agent": "LanwatchAgent/1.0"})
        rtt = (time.time() - start) * 1000
        title = None
        try:
            if "text/html" in response.headers.get("content-type", ""):
                import re
                m = re.search(r"<title>([^<]+)</title>", response.text, re.IGNORECASE)
                if m:
                    title = m.group(1).strip()
        except Exception as e:
            logger.warning("HTML 标题提取失败 [%s]: %s", url, e)
        return {
            "url": url, "status_code": response.status_code,
            "response_time_ms": round(rtt, 2), "reachable": True, "error": None,
            "title": title
        }
    except httpx.TimeoutException:
        return {"url": url, "status_code": None, "response_time_ms": None, "reachable": False, "error": "超时", "title": None}
    except httpx.ConnectError as e:
        return {"url": url, "status_code": None, "response_time_ms": None, "reachable": False, "error": f"连接失败: {e}", "title": None}
    except Exception as e:
        return {"url": url, "status_code": None, "response_time_ms": None, "reachable": False, "error": str(e), "title": None}


def check_urls(urls: list, timeout: float = 5.0) -> Dict[str, Dict]:
    """批量检查多个 URL"""
    results = {}
    for url in urls:
        results[url] = check_url(url, timeout)
    return results
