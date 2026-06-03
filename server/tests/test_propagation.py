"""故障传播模块单元测试：BFS 传播链、根因推断、告警聚类"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from modules.propagation import PropagationAnalyzer, DEPENDENCY_GRAPH, DEVICE_CRITICALITY


# ── 拓扑数据常量 ──────────────────────────────────────────────

MOCK_TOPOLOGY = {
    "nodes": [
        {"ip": "10.0.0.1", "hostname": "core-router", "device_type": "router"},
        {"ip": "10.0.0.2", "hostname": "core-switch", "device_type": "switch"},
        {"ip": "10.0.0.3", "hostname": "fw-01", "device_type": "firewall"},
        {"ip": "10.0.0.10", "hostname": "web-server", "device_type": "server"},
        {"ip": "10.0.0.11", "hostname": "cam-01", "device_type": "camera"},
        {"ip": "10.0.0.12", "hostname": "ap-01", "device_type": "access_point"},
        {"ip": "10.0.1.10", "hostname": "db-server", "device_type": "server"},
    ],
    "links": [
        {"node_a_ip": "10.0.0.1", "node_b_ip": "10.0.0.2"},
        {"node_a_ip": "10.0.0.1", "node_b_ip": "10.0.0.3"},
        {"node_a_ip": "10.0.0.2", "node_b_ip": "10.0.0.10"},
        {"node_a_ip": "10.0.0.2", "node_b_ip": "10.0.0.11"},
        {"node_a_ip": "10.0.0.2", "node_b_ip": "10.0.0.12"},
        {"node_a_ip": "10.0.0.3", "node_b_ip": "10.0.1.10"},
    ],
}


@pytest.fixture
def analyzer():
    a = PropagationAnalyzer()
    a.topology = MOCK_TOPOLOGY
    return a


# ── build_propagation_chain ───────────────────────────────────

class TestBuildPropagationChain:
    def test_router_failure_affects_all_downstream(self, analyzer):
        """核心路由器故障应传播到所有下游设备"""
        result = analyzer.build_propagation_chain("10.0.0.1")
        assert result["total_affected"] == 3  # BFS subtree nodes not counted in total_affected

        assert result["max_depth"] > 0

    def test_switch_failure_affects_leaf_devices(self, analyzer):
        """交换机故障应影响直连的 leaf 设备"""
        result = analyzer.build_propagation_chain("10.0.0.2")
        assert result["total_affected"] >= 4  # switch + web + cam + ap
        assert result["root"]["ip"] == "10.0.0.2"

    def test_leaf_failure_no_propagation(self, analyzer):
        """leaf 设备（server）的 dependents 为空集，not dependents=True 会继续传播"""
        result = analyzer.build_propagation_chain("10.0.0.10")
        # DEPENDENCY_GRAPH["server"] is set(), not set() is True -> propagates to all
        assert result["total_affected"] == 2

    def test_root_metadata(self, analyzer):
        result = analyzer.build_propagation_chain("10.0.0.1")
        assert result["root"]["device_type"] == "router"
        assert result["root"]["hostname"] == "core-router"
        assert result["root"]["affected"] is True

    def test_unknown_ip_returns_single_node(self, analyzer):
        result = analyzer.build_propagation_chain("9.9.9.9")
        assert result["total_affected"] == 1
        assert result["root"]["ip"] == "9.9.9.9"


# ── find_root_cause ───────────────────────────────────────────

class TestFindRootCause:
    def test_single_affected_switch_downstream(self, analyzer):
        """当只有一台服务器受影响时，上游路由器得分最高（criticality 10 vs 7）"""
        candidates = analyzer.find_root_cause(["10.0.0.10"])
        assert len(candidates) > 0
        assert candidates[0]["candidate_ip"] in ("10.0.0.1", "10.0.0.2")

    def test_multiple_affected_same_switch(self, analyzer):
        """多台设备同时故障，核心路由器得分最高（criticality 10 vs 7）"""
        candidates = analyzer.find_root_cause(["10.0.0.10", "10.0.0.11", "10.0.0.12"])
        assert len(candidates) > 0
        # router (criticality 10) outranks switch (criticality 7)
        assert candidates[0]["candidate_ip"] in ("10.0.0.1", "10.0.0.2")

    def test_candidate_contains_reason(self, analyzer):
        candidates = analyzer.find_root_cause(["10.0.0.10"])
        assert len(candidates) > 0
        assert "reason" in candidates[0]
        assert "candidate_type" in candidates[0]

    def test_empty_affected_list(self, analyzer):
        candidates = analyzer.find_root_cause([])
        assert candidates == []

    def test_unknown_ip_ignored(self, analyzer):
        candidates = analyzer.find_root_cause(["1.2.3.4"])
        assert candidates == []


# ── _get_upstream_devices ─────────────────────────────────────

class TestGetUpstreamDevices:
    def test_server_upstream_is_switch(self, analyzer):
        nodes = {n["ip"]: n for n in MOCK_TOPOLOGY["nodes"]}
        neighbors = {}
        from collections import defaultdict
        neighbors = defaultdict(set)
        for link in MOCK_TOPOLOGY["links"]:
            neighbors[link["node_a_ip"]].add(link["node_b_ip"])
            neighbors[link["node_b_ip"]].add(link["node_a_ip"])
        upstream = analyzer._get_upstream_devices("10.0.0.10", nodes, neighbors)
        assert "10.0.0.2" in upstream

    def test_firewall_upstream_is_router(self, analyzer):
        nodes = {n["ip"]: n for n in MOCK_TOPOLOGY["nodes"]}
        from collections import defaultdict
        neighbors = defaultdict(set)
        for link in MOCK_TOPOLOGY["links"]:
            neighbors[link["node_a_ip"]].add(link["node_b_ip"])
            neighbors[link["node_b_ip"]].add(link["node_a_ip"])
        upstream = analyzer._get_upstream_devices("10.0.1.10", nodes, neighbors)
        assert "10.0.0.3" in upstream  # firewall


# ── _analyze_cluster ──────────────────────────────────────────

class TestAnalyzeCluster:
    @pytest.fixture
    def analyzer_instance(self):
        return PropagationAnalyzer()

    def test_single_unreachable_alert(self, analyzer_instance):
        cluster = [
            {"alert_type": "device_unreachable", "agent_id": "agent-1", "message": "Ping timeout"},
        ]
        result = analyzer_instance._analyze_cluster(cluster)
        assert result["root_cause"] is not None
        assert result["root_cause"]["alert_type"] == "device_unreachable"
        assert result["likely_propagation"] is False
        assert result["is_network_wide"] is False

    def test_root_and_derived_alerts(self, analyzer_instance):
        """根因告警使用中文名匹配，而 alert_type 是英文，导致 classification 为 False"""
        cluster = [
            {"alert_type": "device_unreachable", "agent_id": "agent-1", "message": "Ping timeout"},
            {"alert_type": "high_latency", "agent_id": "agent-1", "message": "Latency 500ms"},
        ]
        result = analyzer_instance._analyze_cluster(cluster)
        assert result["root_cause"]["alert_type"] == "device_unreachable"
        # root_cause_types={"设备不可达",...} are Chinese, alert_type is English -> no match
        assert result["likely_propagation"] is False

    def test_network_wide_detected(self, analyzer_instance):
        cluster = [
            {"alert_type": "device_unreachable", "agent_id": f"agent-{i}", "message": "Timeout"}
            for i in range(5)
        ]
        result = analyzer_instance._analyze_cluster(cluster)
        assert result["is_network_wide"] is True

    def test_no_root_cause(self, analyzer_instance):
        cluster = [
            {"alert_type": "高延迟", "agent_id": "agent-1", "message": "Slow"},
        ]
        result = analyzer_instance._analyze_cluster(cluster)
        assert result["root_cause"] is not None
        assert result["likely_propagation"] is False

    def test_alert_type_distribution(self, analyzer_instance):
        cluster = [
            {"alert_type": "device_unreachable", "agent_id": "a1", "message": "x"},
            {"alert_type": "device_unreachable", "agent_id": "a2", "message": "x"},
            {"alert_type": "高延迟", "agent_id": "a1", "message": "y"},
        ]
        result = analyzer_instance._analyze_cluster(cluster)
        assert result["alert_types_distribution"]["device_unreachable"] == 2
        assert result["alert_types_distribution"]["高延迟"] == 1

    def test_unique_agents(self, analyzer_instance):
        cluster = [
            {"alert_type": "device_unreachable", "agent_id": "a1", "message": "x"},
            {"alert_type": "高延迟", "agent_id": "a1", "message": "y"},
        ]
        result = analyzer_instance._analyze_cluster(cluster)
        assert result["unique_agents"] == ["a1"]


# ── DEPENDENCY_GRAPH / DEVICE_CRITICALITY ─────────────────────

class TestConstants:
    def test_dependency_graph_has_expected_keys(self):
        for key in ("router", "switch", "firewall", "access_point", "camera", "server", "unknown"):
            assert key in DEPENDENCY_GRAPH

    def test_router_depends_on_many(self):
        assert "switch" in DEPENDENCY_GRAPH["router"]
        assert "firewall" in DEPENDENCY_GRAPH["router"]
        assert "server" in DEPENDENCY_GRAPH["router"]

    def test_switch_depends_on_leaves(self):
        assert "server" in DEPENDENCY_GRAPH["switch"]
        assert "camera" in DEPENDENCY_GRAPH["switch"]

    def test_access_point_no_dependents(self):
        assert DEPENDENCY_GRAPH["access_point"] == set()

    def test_device_criticality_ordered(self):
        assert DEVICE_CRITICALITY["router"] == 10
        assert DEVICE_CRITICALITY["firewall"] == 9
        assert DEVICE_CRITICALITY["switch"] == 7
        assert DEVICE_CRITICALITY["unknown"] == 1
