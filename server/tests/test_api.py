"""服务端 API 单元测试"""
import pytest, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.database import init_db
init_db()  # TestClient 不会触发 lifespan，需手动初始化数据库

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_root():
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")


def test_register():
    r = client.post("/register", json={
        "agent_id": "test-agent-001",
        "name": "测试Agent",
        "ip": "192.168.1.100",
        "os_type": "linux"
    })
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is True
    assert "agent_token" in data


def test_register_idempotent():
    """幂等测试：同一 agent_id 重复注册返回已有 token"""
    payload = {"agent_id": "test-agent-002", "name": "测试2", "os_type": "windows"}
    r1 = client.post("/register", json=payload)
    token1 = r1.json()["agent_token"]

    r2 = client.post("/register", json=payload)
    token2 = r2.json()["agent_token"]

    assert r2.status_code == 200
    assert token1 == token2  # token 不变


def test_get_agents():
    r = client.get("/agents")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_probe_ping():
    r = client.get("/api/probe/ping", params={"host": "8.8.8.8", "count": 2})
    assert r.status_code == 200
    data = r.json()
    assert "host" in data
    assert "loss_rate" in data
    assert "status" in data


def test_probe_portscan():
    r = client.get("/api/probe/portscan", params={"host": "8.8.8.8", "ports": "80,443"})
    assert r.status_code == 200
    data = r.json()
    assert "results" in data
    assert "80" in data["results"]
    assert "443" in data["results"]


def test_probe_dns():
    r = client.get("/api/probe/dns", params={"domain": "www.baidu.com"})
    assert r.status_code == 200
    data = r.json()
    assert data["domain"] == "www.baidu.com"
    assert "results" in data


def test_probe_http():
    r = client.get("/api/probe/http", params={"url": "https://www.baidu.com"})
    assert r.status_code == 200
    data = r.json()
    assert data["reachable"] is True
    assert data["status_code"] == 200


def test_probe_traceroute():
    r = client.get("/api/probe/traceroute", params={"target": "8.8.8.8", "max_hops": 5})
    assert r.status_code == 200
    data = r.json()
    assert "hops" in data
    assert isinstance(data["hops"], list)


def test_protected_endpoint_without_token():
    """report 接口无 token 应返回 401"""
    r = client.post("/test-agent-001/report", json=[])
    assert r.status_code == 401


def test_protected_endpoint_invalid_token():
    """report 接口无效 token 应返回 401"""
    r = client.post("/test-agent-001/report",
                     json=[],
                     headers={"Authorization": "Bearer invalid_token_123"})
    assert r.status_code == 401
