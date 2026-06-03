"""探测模块单元测试（不依赖网络）"""
import pytest, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from modules.ping import ping_once
from modules.portscan import check_port, scan_ports
from modules.http_check import check_url


def test_ping_localhost():
    """ping 本地回环地址应该成功"""
    ok, rtt = ping_once("127.0.0.1", timeout=2)
    assert ok is True
    assert rtt is None or rtt >= 0


def test_ping_nonexistent():
    """ping 不存在的 IP 应该返回不可达（快速失败）"""
    import time
    start = time.time()
    ok, rtt = ping_once("192.0.2.1", timeout=2)  # TEST-NET-1，应快速返回
    elapsed = time.time() - start
    assert elapsed < 5  # 不应该超时很久


def test_portscan_localhost():
    """扫描本机端口"""
    result = check_port("127.0.0.1", 80, timeout=3)
    assert result["port"] == 80
    assert result["status"] in ["open", "closed"]


def test_http_check_invalid_url():
    """无效 URL 应该优雅失败"""
    result = check_url("http://this-domain-definitely-does-not-exist-12345.com", timeout=3)
    assert result["reachable"] is False
    assert result["error"] is not None


# ── module-level tests ─────────────────────────────────────────

class TestPortScanUtils:
    """端口扫描模块纯函数测试"""

    def test_check_port_localhost_80(self):
        from modules.portscan import check_port
        result = check_port("127.0.0.1", 80, timeout=2)
        assert result["port"] == 80
        assert result["status"] in ("open", "closed", "filtered")

    def test_check_port_invalid_host(self):
        from modules.portscan import check_port
        result = check_port("192.0.2.1", 80, timeout=2)
        assert result["port"] == 80


class TestDnsUtils:
    """DNS 测试模块基本验证"""

    def test_dns_servers_defined(self):
        from modules.dns_test import DNS_SERVERS
        assert len(DNS_SERVERS) >= 3
        assert "114.114.114.114" in DNS_SERVERS
        assert "8.8.8.8" in DNS_SERVERS

    def test_resolve_custom_invalid_server(self):
        from modules.dns_test import resolve_custom
        result = resolve_custom("example.com", dns_server="192.0.2.1")
        assert result["success"] is False
        assert result["domain"] == "example.com"


class TestHttpCheckUtils:
    """HTTP 检查模块基本验证"""

    def test_check_url_invalid(self):
        from modules.http_check import check_url
        result = check_url("http://192.0.2.1:1/", timeout=2)
        assert result["reachable"] is False
        assert result["error"] is not None

    def test_check_url_empty_url(self):
        from modules.http_check import check_url
        result = check_url("", timeout=2)
        assert result["reachable"] is False


class TestTracerouteUtils:
    """Traceroute 模块基本验证"""

    def test_traceroute_localhost(self):
        from modules.traceroute import traceroute
        # local traceroute should at least return a result
        result = traceroute("127.0.0.1", max_hops=5, timeout=2)
        assert isinstance(result, list)
        # On Linux/macOS, traceroute to localhost usually shows 1 hop
        if result:
            assert result[0]["ttl"] == 1
            assert result[0]["ip"] in ("127.0.0.1", "")
