"""故障传播链分析：基于拓扑的故障传播建模、根因推断、影响范围分析"""
import logging
from typing import Dict, List, Any, Optional, Set, Tuple
from datetime import datetime, timedelta
from collections import defaultdict

from core.database import get_db
from modules.topology import topology_manager

logger = logging.getLogger("propagation")

# ===== 故障传播规则 =====
DEPENDENCY_GRAPH = {
    "router": {"switch", "firewall", "server", "access_point", "camera", "unknown"},
    "switch": {"server", "camera", "access_point", "unknown"},
    "firewall": {"server", "switch"},
    "access_point": set(),
    "camera": set(),
    "server": set(),
    "unknown": {"router", "switch", "firewall", "server", "access_point", "camera"},
}

DEVICE_CRITICALITY = {
    "router": 10,
    "firewall": 9,
    "switch": 7,
    "access_point": 5,
    "camera": 3,
    "server": 4,
    "unknown": 1,
}


class PropagationAnalyzer:
    """故障传播链分析器。给定一个故障设备，分析它可能影响哪些下游设备。"""

    def __init__(self):
        self.topology = None  # 缓存拓扑数据

    def _load_topology(self):
        """加载拓扑数据（延迟加载）"""
        if self.topology is None:
            self.topology = topology_manager.get_topology()
        return self.topology

    def find_root_cause(
        self,
        affected_ips: List[str],
    ) -> List[Dict[str, Any]]:
        """给定一组受影响设备的 IP，寻找最可能的根因设备。"""
        topo = self._load_topology()
        nodes = {n["ip"]: n for n in topo.get("nodes", [])}
        links = topo.get("links", [])

        neighbors: Dict[str, Set[str]] = defaultdict(set)
        for link in links:
            neighbors[link.get("node_a_ip", "")].add(link.get("node_b_ip", ""))
            neighbors[link.get("node_b_ip", "")].add(link.get("node_a_ip", ""))

        candidates = []

        for ip in affected_ips:
            if ip not in nodes:
                continue

            node = nodes[ip]
            device_type = node.get("device_type", "unknown")
            upstream = self._get_upstream_devices(ip, nodes, neighbors)

            for upstream_ip in upstream:
                if upstream_ip in affected_ips:
                    continue

                upstream_node = nodes.get(upstream_ip, {})
                upstream_type = upstream_node.get("device_type", "unknown")
                upstream_critical = DEVICE_CRITICALITY.get(upstream_type, 1)

                score = upstream_critical * 2 + len([
                    n for n in neighbors.get(upstream_ip, []) if n in affected_ips
                ])

                candidates.append({
                    "candidate_ip": upstream_ip,
                    "candidate_type": upstream_type,
                    "candidate_hostname": upstream_node.get("hostname", ""),
                    "affected_devices": [
                        n for n in neighbors.get(upstream_ip, []) if n in affected_ips
                    ],
                    "score": score,
                    "reason": f"{upstream_type} 设备故障可能影响其下游设备",
                })

        candidates.sort(key=lambda x: x["score"], reverse=True)
        return candidates[:5]

    def _get_upstream_devices(
        self,
        ip: str,
        nodes: Dict[str, Dict],
        neighbors: Dict[str, Set[str]],
    ) -> Set[str]:
        """获取某设备的上游设备（拓扑链路上游）"""
        upstream = set()
        visited = set()

        def dfs(current: str, depth: int = 0):
            if depth > 3 or current in visited:
                return
            visited.add(current)

            for neighbor in neighbors.get(current, []):
                neighbor_type = nodes.get(neighbor, {}).get("device_type", "unknown")
                if neighbor_type in ("router", "firewall", "switch"):
                    upstream.add(neighbor)
                dfs(neighbor, depth + 1)

        dfs(ip)
        return upstream

    def build_propagation_chain(
        self,
        root_ip: str,
        depth: int = 3,
    ) -> Dict[str, Any]:
        """给定根因设备，构建故障传播链（BFS 向下游传播）。"""
        topo = self._load_topology()
        nodes = {n["ip"]: n for n in topo.get("nodes", [])}
        links = topo.get("links", [])

        neighbors: Dict[str, Set[str]] = defaultdict(set)
        for link in links:
            neighbors[link.get("node_a_ip", "")].add(link.get("node_b_ip", ""))
            neighbors[link.get("node_b_ip", "")].add(link.get("node_a_ip", ""))

        root_node = nodes.get(root_ip, {})
        root_type = root_node.get("device_type", "unknown")

        chain = {
            "root": {
                "ip": root_ip,
                "hostname": root_node.get("hostname", ""),
                "device_type": root_type,
                "affected": True,
                "children": [],
            },
            "total_affected": 1,
            "max_depth": 0,
        }

        visited = {root_ip}
        queue = [(root_ip, 0)]

        while queue:
            current, depth_cur = queue.pop(0)
            current_type = nodes.get(current, {}).get("device_type", "unknown")
            dependents = DEPENDENCY_GRAPH.get(current_type, set())

            for neighbor in neighbors.get(current, []):
                if neighbor in visited:
                    continue

                neighbor_type = nodes.get(neighbor, {}).get("device_type", "unknown")

                if neighbor_type in dependents or not dependents:
                    visited.add(neighbor)
                    chain["total_affected"] += 1
                    chain["max_depth"] = max(chain["max_depth"], depth_cur + 1)

                    subtree = self._build_subtree(
                        neighbor, visited, neighbors, nodes, depth_cur + 1, depth,
                    )
                    chain["root"]["children"].append(subtree)
                    queue.append((neighbor, depth_cur + 1))

        return chain

    def _build_subtree(
        self,
        ip: str,
        visited: Set[str],
        neighbors: Dict[str, Set[str]],
        nodes: Dict[str, Dict],
        depth: int,
        max_depth: int,
    ) -> Dict[str, Any]:
        """递归构建传播子树"""
        node = nodes.get(ip, {})
        node_type = node.get("device_type", "unknown")
        dependents = DEPENDENCY_GRAPH.get(node_type, set())

        subtree = {
            "ip": ip,
            "hostname": node.get("hostname", ""),
            "device_type": node_type,
            "affected": True,
            "children": [],
        }

        if depth >= max_depth:
            return subtree

        for neighbor in neighbors.get(ip, []):
            if neighbor in visited:
                continue

            neighbor_type = nodes.get(neighbor, {}).get("device_type", "unknown")
            if neighbor_type in dependents or not dependents:
                visited.add(neighbor)
                subtree["children"].append(
                    self._build_subtree(neighbor, visited, neighbors, nodes, depth + 1, max_depth),
                )

        return subtree

    def correlate_alerts(
        self,
        agent_id: Optional[str] = None,
        hours: int = 24,
    ) -> Dict[str, Any]:
        """告警关联分析：
        - 找出时间上接近的告警（可能在同一故障中）
        - 按空间（同一设备/相邻设备）聚类
        - 识别可能的根因告警和派生告警
        """
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()

        with get_db() as conn:
            cursor = conn.cursor()
            sql = "SELECT * FROM alert_log WHERE created_at >= ?"
            params: list = [cutoff]

            if agent_id:
                sql += " AND agent_id = ?"
                params.append(agent_id)

            sql += " ORDER BY created_at ASC"
            cursor.execute(sql, params)
            alerts = [dict(row) for row in cursor.fetchall()]

        if not alerts:
            return {"clusters": [], "total_alerts": 0, "cluster_count": 0}

        # 按时间窗口聚类（5分钟内相近的告警归为一组）
        clusters: List[List[Dict]] = []
        current_cluster: List[Dict] = []

        for alert in alerts:
            if not current_cluster:
                current_cluster.append(alert)
            else:
                last_time = datetime.fromisoformat(current_cluster[-1]["created_at"])
                curr_time = datetime.fromisoformat(alert["created_at"])
                diff_seconds = (curr_time - last_time).total_seconds()

                if diff_seconds < 300:  # 5 分钟内
                    current_cluster.append(alert)
                else:
                    clusters.append(current_cluster)
                    current_cluster = [alert]

        if current_cluster:
            clusters.append(current_cluster)

        # 分析每个聚类
        analyzed_clusters = []
        for i, cluster in enumerate(clusters):
            analyzed = self._analyze_cluster(cluster)
            analyzed_clusters.append({
                "cluster_id": i + 1,
                "alert_count": len(cluster),
                "time_range": {
                    "first": cluster[0]["created_at"],
                    "last": cluster[-1]["created_at"],
                },
                "affected_ips": list(set(a.get("agent_id", "") for a in cluster)),
                "analysis": analyzed,
            })

        analyzed_clusters.sort(key=lambda x: x["alert_count"], reverse=True)

        return {
            "total_alerts": len(alerts),
            "cluster_count": len(clusters),
            "clusters": analyzed_clusters,
        }

    def _analyze_cluster(self, cluster: List[Dict]) -> Dict[str, Any]:
        """分析单个告警聚类"""
        alert_types = [a.get("alert_type", "") for a in cluster]
        agent_ids = list(set(a.get("agent_id", "") for a in cluster))

        type_counts: Dict[str, int] = defaultdict(int)
        for t in alert_types:
            type_counts[t] += 1

        root_cause_types = {"设备不可达", "设备离线", "宕机"}
        derived_types = {"延迟高", "丢包", "响应慢", "服务异常"}

        root_alerts = [
            a for a in cluster
            if any(rc in a.get("alert_type", "") for rc in root_cause_types)
        ]
        derived_alerts = [
            a for a in cluster
            if any(d in a.get("alert_type", "") for d in derived_types)
        ]

        primary_cause = None
        if root_alerts:
            primary_cause = root_alerts[0]
        elif cluster:
            primary_cause = cluster[0]

        return {
            "root_cause": {
                "alert_type": primary_cause.get("alert_type") if primary_cause else None,
                "agent_id": primary_cause.get("agent_id") if primary_cause else None,
                "message": primary_cause.get("message") if primary_cause else None,
            } if primary_cause else None,
            "alert_types_distribution": dict(type_counts),
            "unique_agents": agent_ids,
            "is_network_wide": len(agent_ids) > 3,
            "likely_propagation": len(derived_alerts) > 0 and len(root_alerts) > 0,
        }


propagation_analyzer = PropagationAnalyzer()
