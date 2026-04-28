"""
诊断引擎测试
"""
import pytest
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.database import init_db
from modules.diagnosis import diagnosis_engine, DIAGNOSIS_RULES
from fastapi.testclient import TestClient
from main import app

init_db()

client = TestClient(app)


def test_diagnosis_rules_count():
    assert len(DIAGNOSIS_RULES) >= 10


def test_diagnose_ping_100_loss():
    result = {"received": 0, "loss_rate": 1.0, "avg_rtt_ms": None}
    diagnoses = diagnosis_engine.diagnose("ping", "192.168.1.1", result)
    assert len(diagnoses) > 0
    rule_ids = [d["rule_id"] for d in diagnoses]
    assert "ping_100_loss" in rule_ids


def test_diagnose_ping_high_latency():
    result = {"received": 4, "loss_rate": 0.0, "avg_rtt_ms": 500}
    diagnoses = diagnosis_engine.diagnose("ping", "8.8.8.8", result)
    rule_ids = [d["rule_id"] for d in diagnoses]
    assert "ping_high_latency" in rule_ids


def test_diagnose_http_unreachable():
    result = {"reachable": False, "error": "Connection refused"}
    diagnoses = diagnosis_engine.diagnose("http", "https://example.com", result)
    rule_ids = [d["rule_id"] for d in diagnoses]
    assert "http_unreachable" in rule_ids


def test_diagnose_dns_all_fail():
    result = {"results": {"8.8.8.8": {"success": False}, "1.1.1.1": {"success": False}}}
    diagnoses = diagnosis_engine.diagnose("dns", "example.com", result)
    rule_ids = [d["rule_id"] for d in diagnoses]
    assert "dns_all_fail" in rule_ids


def test_diagnose_no_issue():
    result = {"received": 4, "loss_rate": 0.0, "avg_rtt_ms": 10}
    diagnoses = diagnosis_engine.diagnose("ping", "8.8.8.8", result)
    assert len(diagnoses) == 0


def test_api_diagnose_endpoint():
    r = client.post("/api/diagnosis/diagnose", json={
        "probe_type": "ping",
        "target": "192.168.1.1",
        "result": {"received": 0, "loss_rate": 1.0},
    })
    assert r.status_code == 200
    data = r.json()
    assert data["has_issues"] is True
    assert len(data["diagnoses"]) > 0


def test_api_diagnose_no_issue():
    r = client.post("/api/diagnosis/diagnose", json={
        "probe_type": "ping",
        "target": "8.8.8.8",
        "result": {"received": 4, "loss_rate": 0.0, "avg_rtt_ms": 5},
    })
    assert r.status_code == 200
    data = r.json()
    assert data["has_issues"] is False


def test_diagnosis_causes_sorted_by_probability():
    result = {"received": 0, "loss_rate": 1.0}
    diagnoses = diagnosis_engine.diagnose("ping", "192.168.1.1", result)
    if diagnoses:
        for d in diagnoses:
            causes = d["possible_causes"]
            probs = [c["probability"] for c in causes]
            assert probs == sorted(probs, reverse=True)


def test_diagnosis_has_steps():
    result = {"received": 0, "loss_rate": 1.0}
    diagnoses = diagnosis_engine.diagnose("ping", "192.168.1.1", result)
    if diagnoses:
        assert len(diagnoses[0]["diagnostic_steps"]) > 0
        assert len(diagnoses[0]["recommended_actions"]) > 0
