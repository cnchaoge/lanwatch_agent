"""
版本和系统端点测试
"""
import pytest
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient
from main import app
from core.database import init_db, config

init_db()

client = TestClient(app)


def test_health_endpoint():
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"


def test_version_endpoint():
    r = client.get("/api/version")
    assert r.status_code == 200
    data = r.json()
    assert "version" in data
    assert data["version"] == "1.0.0"
    assert "author" in data
    assert "license" in data


def test_root_returns_html():
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")


def test_wizard_scenarios():
    r = client.get("/api/wizard/scenarios")
    assert r.status_code == 200
    data = r.json()
    assert len(data["scenarios"]) >= 5


def test_diagnosis_rules():
    r = client.get("/api/diagnosis/rules")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] >= 10


def test_alert_channels():
    r = client.get("/api/alerts/channels")
    assert r.status_code == 200
    data = r.json()
    assert "serverchan" in data
    assert "dingtalk" in data
    assert "feishu" in data


def test_topology_stats():
    r = client.get("/api/topology/stats")
    assert r.status_code == 200
    data = r.json()
    assert "total_nodes" in data
    assert "total_links" in data


def test_scheduler_jobs():
    r = client.get("/api/scheduler/jobs")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)


def test_propagation_correlate():
    r = client.get("/api/propagation/correlate?hours=24")
    assert r.status_code == 200
    data = r.json()
    assert "cluster_count" in data


def test_snmp_devices_list():
    r = client.get("/api/snmp/devices/nonexistent-agent")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 0
