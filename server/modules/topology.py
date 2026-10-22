"""网络拓扑管理模块：节点/链路持久化

v1.3.x: 移除 SNMP/LLDP/CDP 自动发现（pysnmp 已下线，client 无对应能力）。
保留 TopologyManager 的 DB 持久化层，供将来手动导入拓扑使用。
"""
import logging
from typing import Dict, Any, Optional
from datetime import datetime
from core.database import get_db

logger = logging.getLogger("topology")


class TopologyManager:
    """拓扑管理器：持久化和查询拓扑数据"""

    _instance: Optional["TopologyManager"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @staticmethod
    def save_topology(agent_id: str, nodes: list, links: list):
        """保存拓扑数据到数据库"""
        now = datetime.now().isoformat()
        with get_db() as conn:
            cursor = conn.cursor()
            for node in nodes:
                cursor.execute(
                    """INSERT OR REPLACE INTO topology_nodes
                       (agent_id, ip, mac, hostname, device_type, vendor, raw_data, last_seen)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        agent_id,
                        node.get("ip", ""),
                        node.get("mac", ""),
                        node.get("hostname", ""),
                        node.get("device_type", "unknown"),
                        node.get("vendor", "Unknown"),
                        str(node.get("raw_data", {})),
                        now,
                    ),
                )
            for link in links:
                cursor.execute(
                    """INSERT OR REPLACE INTO topology_links
                       (node_a_ip, node_a_port, node_b_ip, node_b_port, link_type, last_confirmed)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        link.get("from_ip", ""),
                        link.get("from_port", ""),
                        link.get("to_ip", ""),
                        link.get("to_port", ""),
                        link.get("link_type", "unknown"),
                        now,
                    ),
                )
        logger.info("保存拓扑: %d 节点, %d 链路", len(nodes), len(links))

    @staticmethod
    def get_topology(agent_id: Optional[str] = None) -> Dict[str, Any]:
        """获取拓扑数据"""
        with get_db() as conn:
            cursor = conn.cursor()
            if agent_id:
                cursor.execute(
                    "SELECT * FROM topology_nodes WHERE agent_id = ? ORDER BY last_seen DESC",
                    (agent_id,),
                )
            else:
                cursor.execute("SELECT * FROM topology_nodes ORDER BY last_seen DESC")
            nodes = [dict(row) for row in cursor.fetchall()]
            cursor.execute("SELECT * FROM topology_links")
            links = [dict(row) for row in cursor.fetchall()]
        return {"nodes": nodes, "links": links, "count": len(nodes)}


topology_manager = TopologyManager()
