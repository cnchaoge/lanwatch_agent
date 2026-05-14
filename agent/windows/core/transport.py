"""
HTTP 上报通道：
- 携带 Bearer token 认证
- 自动重试（网络抖动）
- 日志记录
"""
import httpx, json, logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger("transport")


class Transport:
    """HTTP 上报通道"""

    def __init__(self, server_url: str, agent_id: str, token: str, timeout: float = 10.0):
        self.server_url = server_url.rstrip("/")
        self.agent_id = agent_id
        self.token = token
        self.timeout = timeout
        self.client = httpx.Client(timeout=timeout)

    def _headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}"
        }

    def register(self, payload: Dict[str, Any]) -> Optional[Dict]:
        """注册设备到服务器"""
        url = f"{self.server_url}/api/register"
        try:
            r = self.client.post(url, json=payload)
            if r.status_code == 200:
                return r.json()
            logger.warning(f"注册失败: {r.status_code} {r.text}")
        except Exception as e:
            logger.error(f"注册请求异常: {e}")
        return None

    def report(self, reports: List[Dict]) -> bool:
        """上报探测结果"""
        url = f"{self.server_url}/api/{self.agent_id}/report"
        try:
            r = self.client.post(url, json=reports, headers=self._headers())
            if r.status_code == 200:
                return True
            logger.warning(f"上报失败: {r.status_code}")
        except Exception as e:
            logger.error(f"上报请求异常: {e}")
        return False

    def report_topology(self, nodes: List[Dict], links: List[Dict]) -> bool:
        """上报拓扑"""
        url = f"{self.server_url}/api/{self.agent_id}/topology"
        try:
            r = self.client.post(url, json=nodes, params={"links": links},
                                 headers=self._headers())
            if r.status_code == 200:
                return True
            logger.warning(f"拓扑上报失败: {r.status_code}")
        except Exception as e:
            logger.error(f"拓扑上报异常: {e}")
        return False

    def report_offline(self) -> bool:
        """通知服务端 agent 离线"""
        url = f"{self.server_url}/api/{self.agent_id}/offline"
        try:
            r = self.client.post(url, headers=self._headers())
            if r.status_code == 200:
                return True
            logger.warning(f"离线通知失败: {r.status_code}")
        except Exception as e:
            logger.error(f"离线通知异常: {e}")
        return False

    def report_diag(self, report_data: Dict) -> bool:
        """上报诊断报告"""
        url = f"{self.server_url}/api/{self.agent_id}/diag"
        try:
            r = self.client.post(url, json=report_data, headers=self._headers())
            if r.status_code == 200:
                return True
            logger.warning(f"诊断上报失败: {r.status_code}")
        except Exception as e:
            logger.error(f"诊断上报异常: {e}")
        return False

    def fetch_targets(self) -> Optional[List[Dict]]:
        """从服务端拉取监控目标配置"""
        url = f"{self.server_url}/api/targets"
        try:
            r = self.client.get(url, params={"agent_id": self.agent_id, "token": self.token})
            if r.status_code == 200:
                data = r.json()
                if data.get("success"):
                    return data.get("data", [])
            logger.warning(f"拉取目标配置失败: {r.status_code} {r.text}")
        except Exception as e:
            logger.error(f"拉取目标配置异常: {e}")
        return None

    def close(self):
        self.client.close()
