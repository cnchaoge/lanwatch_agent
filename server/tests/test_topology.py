"""拓扑模块单元测试：TopologyManager 的持久化与查询（v1.3.x 起不再有 SNMP 自动发现）"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from modules.topology import topology_manager, TopologyManager


@pytest.fixture(autouse=True)
def _clean_db():
    from core.database import get_db, init_db
    init_db()
    with get_db() as conn:
        conn.execute("DELETE FROM topology_links")
        conn.execute("DELETE FROM topology_nodes")
    yield


# ── 单例 ────────────────────────────────────────────────────────

class TestSingleton:
    def test_singleton_instance(self):
        assert TopologyManager() is topology_manager


# ── save_topology / get_topology ────────────────────────────────

class TestSaveAndGet:
    def test_save_and_get_by_agent(self):
        topology_manager.save_topology(
            agent_id="agent-a",
            nodes=[{"ip": "192.168.1.1", "mac": "aa:bb:cc:dd:ee:01",
                    "hostname": "gw", "device_type": "router", "vendor": "Cisco"}],
            links=[],
        )
        result = topology_manager.get_topology("agent-a")
        assert result["count"] == 1
        assert result["nodes"][0]["ip"] == "192.168.1.1"
        assert result["nodes"][0]["device_type"] == "router"

    def test_save_links(self):
        topology_manager.save_topology(
            agent_id="agent-a",
            nodes=[{"ip": "192.168.1.1"}, {"ip": "192.168.1.2"}],
            links=[{"from_ip": "192.168.1.1", "from_port": "Gi0/1",
                    "to_ip": "192.168.1.2", "to_port": "Gi0/2",
                    "link_type": "ethernet"}],
        )
        result = topology_manager.get_topology("agent-a")
        assert len(result["links"]) == 1
        assert result["links"][0]["node_a_ip"] == "192.168.1.1"
        assert result["links"][0]["node_b_ip"] == "192.168.1.2"

    def test_get_all_agents(self):
        topology_manager.save_topology("agent-a", [{"ip": "10.0.0.1"}], [])
        topology_manager.save_topology("agent-b", [{"ip": "10.0.0.2"}], [])
        result = topology_manager.get_topology()
        assert result["count"] == 2

    def test_unknown_agent_returns_empty(self):
        result = topology_manager.get_topology("nobody")
        assert result["count"] == 0

    def test_resave_replaces_node(self):
        topology_manager.save_topology("agent-a", [{"ip": "10.0.0.1", "hostname": "old"}], [])
        topology_manager.save_topology("agent-a", [{"ip": "10.0.0.1", "hostname": "new"}], [])
        result = topology_manager.get_topology("agent-a")
        assert result["count"] == 1
        assert result["nodes"][0]["hostname"] == "new"
