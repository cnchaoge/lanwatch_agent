"""告警引擎：内置规则、冷却、多渠道推送"""
import os
import time
import json
import httpx
from typing import Dict, List, Optional, Any
from core.database import get_db
from core.config import config

BUILTIN_RULES: List[Dict[str, Any]] = [
    {"type": "device_unreachable", "name": "设备不可达", "level": "error",
     "description": "Ping 探测失败，设备无法响应"},
    {"type": "high_latency", "name": "高延迟", "level": "warning",
     "description": "Ping RTT 超过阈值 (默认 200ms)", "threshold": 200},
    {"type": "packet_loss", "name": "丢包", "level": "warning",
     "description": "Ping 丢包率超过阈值 (默认 20%)", "threshold": 20},
    {"type": "traceroute_timeout", "name": "路由超时", "level": "warning",
     "description": "Traceroute 未在跳数限制内到达目标"},
    {"type": "dns_failure", "name": "DNS 解析失败", "level": "error",
     "description": "DNS 解析无法完成"},
    {"type": "http_unreachable", "name": "HTTP 不可达", "level": "error",
     "description": "HTTP 健康检查失败"},
    {"type": "http_slow", "name": "HTTP 响应慢", "level": "warning",
     "description": "HTTP 响应时间超过阈值 (默认 5s)", "threshold": 5},
    {"type": "port_closed", "name": "端口关闭", "level": "warning",
     "description": "TCP 端口探测未开放"},
]


class AlertCooldown:
    """告警冷却管理器，防止重复推送"""

    def __init__(self, default_cooldown: float = 300):
        self._store: Dict[str, float] = {}
        self.default_cooldown = default_cooldown

    def _key(self, agent_id: str, alert_type: str) -> str:
        return f"{agent_id}:{alert_type}"

    def is_in_cooldown(self, agent_id: str, alert_type: str) -> bool:
        key = self._key(agent_id, alert_type)
        last_time = self._store.get(key, 0.0)
        elapsed = time.time() - last_time
        return elapsed < self.default_cooldown

    def mark_sent(self, agent_id: str, alert_type: str):
        self._store[self._key(agent_id, alert_type)] = time.time()


class AlertEngine:
    """告警引擎：评估探测结果、写入告警日志、多渠道推送"""

    def __init__(self):
        self.cooldown = AlertCooldown(default_cooldown=config.ALERT_COOLDOWN_SECONDS)

    # ------------------------------------------------------------------ dispatch

    def _dispatch_serverchan(self, title: str, content: str):
        sckey = config.SCKEY
        if not sckey:
            return
        try:
            httpx.post(f"https://sctapi.ftqq.com/{sckey}.send",
                       json={"title": title, "desp": content}, timeout=10)
        except Exception:
            pass

    def _dispatch_dingtalk(self, content: str):
        webhook = config.DINGTALK_WEBHOOK
        if not webhook:
            return
        try:
            httpx.post(webhook,
                       json={"msgtype": "text", "text": {"content": content}},
                       timeout=10)
        except Exception:
            pass

    def _dispatch_feishu(self, content: str):
        webhook = config.FEISHU_WEBHOOK
        if not webhook:
            return
        try:
            httpx.post(webhook,
                       json={"msg_type": "text", "content": {"text": content}},
                       timeout=10)
        except Exception:
            pass

    def dispatch(self, alert_type: str, agent_id: str, message: str, level: str = "warning"):
        """写入告警日志并按需推送（受冷却控制）"""
        if self.cooldown.is_in_cooldown(agent_id, alert_type):
            return

        with get_db() as conn:
            conn.execute(
                "INSERT INTO alert_log (agent_id, alert_type, message, level) VALUES (?, ?, ?, ?)",
                (agent_id, alert_type, message, level),
            )

        title = f"[Lanwatch] {alert_type} - {agent_id}"
        self._dispatch_serverchan(title, message)
        self._dispatch_dingtalk(f"{title}\n{message}")
        self._dispatch_feishu(f"{title}\n{message}")

        self.cooldown.mark_sent(agent_id, alert_type)

    # ------------------------------------------------------------- evaluation

    def evaluate_ping_result(self, agent_id: str, result: dict):
        if result.get("status") == "error":
            self.dispatch("device_unreachable", agent_id,
                          result.get("error", "Ping 探测失败"), "error")
            return
        avg_rtt = result.get("avg_rtt", 0)
        loss_rate = result.get("loss_rate", 0)
        if avg_rtt > 200:
            self.dispatch("high_latency", agent_id,
                          f"高延迟: {avg_rtt:.1f}ms", "warning")
        if loss_rate > 20:
            self.dispatch("packet_loss", agent_id,
                          f"丢包率: {loss_rate:.1f}%", "warning")

    def evaluate_traceroute_result(self, agent_id: str, result: dict):
        if result.get("hop_count", 0) == 0:
            self.dispatch("traceroute_timeout", agent_id,
                          "Traceroute 未在跳数限制内到达目标", "warning")

    def evaluate_dns_result(self, agent_id: str, result: dict):
        if result.get("status") == "error" or result.get("error"):
            self.dispatch("dns_failure", agent_id,
                          f"DNS 解析失败: {result.get('error', '未知错误')}", "error")

    def evaluate_http_result(self, agent_id: str, result: dict):
        if not result.get("reachable"):
            self.dispatch("http_unreachable", agent_id,
                          f"HTTP 不可达: {result.get('url', '')}", "error")
            return
        resp_time = result.get("response_time", 0)
        if resp_time > 5:
            self.dispatch("http_slow", agent_id,
                          f"HTTP 响应慢: {resp_time:.1f}s", "warning")

    def evaluate_portscan_result(self, agent_id: str, result: dict, ports: Optional[List[int]] = None):
        if ports is None:
            ports = [80, 443, 22, 3389]
        for port in ports:
            ps = result.get("results", {}).get(str(port), {})
            if isinstance(ps, dict) and not ps.get("open"):
                self.dispatch("port_closed", agent_id,
                              f"端口 {port} 关闭", "warning")


alerter = AlertEngine()
