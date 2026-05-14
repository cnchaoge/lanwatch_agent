"""
HTTP 上报通道：
- 携带 Bearer token 认证
- 使用标准库 urllib，无需 httpx
"""
import json, logging, urllib.request, urllib.error, urllib.parse
from typing import Optional, Dict, Any, List

logger = logging.getLogger("transport")


class Transport:
    """HTTP 上报通道"""

    def __init__(self, server_url: str, agent_id: str, token: str, timeout: float = 10.0):
        self.server_url = server_url.rstrip("/")
        self.agent_id = agent_id
        self.token = token
        self.timeout = timeout

    def _headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}"
        }

    def _request(self, url: str, data: Optional[bytes] = None,
                 headers: Optional[Dict] = None, method: str = "POST") -> Optional[dict]:
        """发送 HTTP 请求并返回 JSON（任何响应码都尝试解析）"""
        try:
            req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            logger.warning("HTTP %s: %s", e.code, body[:200])
            try:
                return json.loads(body)
            except Exception:
                pass
        except Exception as e:
            logger.error("请求异常: %s", e)
        return None

    def register(self, payload: Dict[str, Any]) -> Optional[Dict]:
        url = f"{self.server_url}/api/register"
        return self._request(url, data=json.dumps(payload).encode(),
                             headers={"Content-Type": "application/json"})

    def report(self, reports: List[Dict]) -> bool:
        url = f"{self.server_url}/api/{self.agent_id}/report"
        r = self._request(url, data=json.dumps(reports).encode(), headers=self._headers())
        return r is not None

    def report_topology(self, nodes: List[Dict], links: List[Dict]) -> bool:
        url = f"{self.server_url}/api/{self.agent_id}/topology"
        params = urllib.parse.urlencode({"links": json.dumps(links)})
        r = self._request(f"{url}?{params}", data=json.dumps(nodes).encode(),
                          headers=self._headers())
        return r is not None

    def report_offline(self) -> bool:
        url = f"{self.server_url}/api/{self.agent_id}/offline"
        r = self._request(url, headers=self._headers())
        return r is not None

    def report_diag(self, report_data: Dict) -> bool:
        url = f"{self.server_url}/api/{self.agent_id}/diag"
        r = self._request(url, data=json.dumps(report_data).encode(),
                          headers=self._headers())
        return r is not None

    def fetch_targets(self) -> Optional[List[Dict]]:
        params = urllib.parse.urlencode({"agent_id": self.agent_id, "token": self.token})
        url = f"{self.server_url}/api/targets?{params}"
        r = self._request(url, method="GET")
        if r and r.get("success"):
            return r.get("data", [])
        return None

    def close(self):
        pass
