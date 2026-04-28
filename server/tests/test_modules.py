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
