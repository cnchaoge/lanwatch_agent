"""告警引擎单元测试：冷却逻辑、告警规则评估"""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch
from modules.alerter import AlertCooldown, AlertEngine


class TestAlertCooldown:
    """AlertCooldown 冷却管理器测试"""

    def test_not_in_cooldown_initially(self):
        cd = AlertCooldown(default_cooldown=300)
        assert cd.is_in_cooldown("agent-1", "device_unreachable") is False

    def test_in_cooldown_after_mark(self):
        cd = AlertCooldown(default_cooldown=300)
        cd.mark_sent("agent-1", "device_unreachable")
        assert cd.is_in_cooldown("agent-1", "device_unreachable") is True

    def test_different_agents_independent(self):
        cd = AlertCooldown(default_cooldown=300)
        cd.mark_sent("agent-1", "device_unreachable")
        assert cd.is_in_cooldown("agent-2", "device_unreachable") is False

    def test_different_types_independent(self):
        cd = AlertCooldown(default_cooldown=300)
        cd.mark_sent("agent-1", "device_unreachable")
        assert cd.is_in_cooldown("agent-1", "high_latency") is False

    def test_cooldown_expires(self):
        cd = AlertCooldown(default_cooldown=0.05)  # 50ms 冷却
        cd.mark_sent("agent-1", "device_unreachable")
        assert cd.is_in_cooldown("agent-1", "device_unreachable") is True
        time.sleep(0.06)
        assert cd.is_in_cooldown("agent-1", "device_unreachable") is False

    def test_mark_updates_existing(self):
        cd = AlertCooldown(default_cooldown=300)
        cd.mark_sent("agent-1", "device_unreachable")
        cd.mark_sent("agent-1", "device_unreachable")  # 再次标记，重置冷却
        assert cd.is_in_cooldown("agent-1", "device_unreachable") is True


class TestAlertEngine:
    """AlertEngine 告警规则评估测试（mock dispatch 避免 DB/HTTP）"""

    @pytest.fixture(autouse=True)
    def _reset_cooldown(self):
        """每个测试重置冷却，避免状态污染"""
        self.engine = AlertEngine()
        self.engine.cooldown = AlertCooldown(default_cooldown=300)

    def test_ping_error_dispatches_unreachable(self):
        with patch.object(self.engine, 'dispatch') as mock_dispatch:
            self.engine.evaluate_ping_result("agent-1", {
                "status": "error",
                "error": "Request timeout",
            })
            mock_dispatch.assert_called_once_with(
                "device_unreachable", "agent-1",
                "Request timeout", "error",
            )

    def test_ping_high_latency(self):
        with patch.object(self.engine, 'dispatch') as mock_dispatch:
            self.engine.evaluate_ping_result("agent-1", {
                "status": "ok", "avg_rtt": 300, "loss_rate": 0,
            })
            mock_dispatch.assert_called_once()
            args = mock_dispatch.call_args[0]
            assert args[0] == "high_latency"

    def test_ping_packet_loss(self):
        with patch.object(self.engine, 'dispatch') as mock_dispatch:
            self.engine.evaluate_ping_result("agent-1", {
                "status": "ok", "avg_rtt": 30, "loss_rate": 50,
            })
            mock_dispatch.assert_called_once()
            args = mock_dispatch.call_args[0]
            assert args[0] == "packet_loss"

    def test_ping_both_latency_and_loss(self):
        """高延迟和丢包应分别告警"""
        with patch.object(self.engine, 'dispatch') as mock_dispatch:
            self.engine.evaluate_ping_result("agent-1", {
                "status": "ok", "avg_rtt": 500, "loss_rate": 80,
            })
            assert mock_dispatch.call_count == 2
            types = [c[0][0] for c in mock_dispatch.call_args_list]
            assert "high_latency" in types
            assert "packet_loss" in types

    def test_ping_normal_no_alert(self):
        with patch.object(self.engine, 'dispatch') as mock_dispatch:
            self.engine.evaluate_ping_result("agent-1", {
                "status": "ok", "avg_rtt": 10, "loss_rate": 0,
            })
            mock_dispatch.assert_not_called()

    def test_dns_failure(self):
        with patch.object(self.engine, 'dispatch') as mock_dispatch:
            self.engine.evaluate_dns_result("agent-1", {
                "status": "error", "error": "DNS timeout",
            })
            mock_dispatch.assert_called_once()
            args = mock_dispatch.call_args[0]
            assert args[0] == "dns_failure"
            assert "DNS timeout" in args[2]

    def test_dns_success_no_alert(self):
        with patch.object(self.engine, 'dispatch') as mock_dispatch:
            self.engine.evaluate_dns_result("agent-1", {
                "status": "ok", "dns_ms": 28,
            })
            mock_dispatch.assert_not_called()

    def test_http_unreachable(self):
        with patch.object(self.engine, 'dispatch') as mock_dispatch:
            self.engine.evaluate_http_result("agent-1", {
                "reachable": False, "url": "https://example.com",
            })
            mock_dispatch.assert_called_once()
            args = mock_dispatch.call_args[0]
            assert args[0] == "http_unreachable"

    def test_http_success_no_alert(self):
        with patch.object(self.engine, 'dispatch') as mock_dispatch:
            self.engine.evaluate_http_result("agent-1", {
                "reachable": True, "response_time": 0.5,
            })
            mock_dispatch.assert_not_called()

    def test_traceroute_timeout(self):
        with patch.object(self.engine, 'dispatch') as mock_dispatch:
            self.engine.evaluate_traceroute_result("agent-1", {
                "hop_count": 0,
            })
            mock_dispatch.assert_called_once()
            args = mock_dispatch.call_args[0]
            assert args[0] == "traceroute_timeout"

    def test_traceroute_success_no_alert(self):
        with patch.object(self.engine, 'dispatch') as mock_dispatch:
            self.engine.evaluate_traceroute_result("agent-1", {
                "hop_count": 10,
            })
            mock_dispatch.assert_not_called()

    def test_dispatch_respects_cooldown(self):
        """同类型告警在冷却期内不重复推送"""
        # 先发一次
        self.engine.dispatch("device_unreachable", "agent-1", "第一次", "error")
        # 立即再发一次同类型
        with patch.object(self.engine, '_dispatch_serverchan') as mock_push:
            self.engine.dispatch("device_unreachable", "agent-1", "第二次", "error")
            mock_push.assert_not_called()

    def test_dispatch_different_types_no_cooldown(self):
        """不同类型告警互不影响"""
        self.engine.dispatch("device_unreachable", "agent-1", "第一次", "error")
        with patch.object(self.engine, '_dispatch_serverchan') as mock_push:
            self.engine.dispatch("high_latency", "agent-1", "第二次", "warning")
            mock_push.assert_called_once()
