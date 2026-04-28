"""网络拓扑发现模块：SNMP/LLDP/CDP 拓扑发现 + 节点/链路持久化"""
import logging
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
from core.database import get_db
from modules.snmp import snmp_get, snmp_bulkwalk

logger = logging.getLogger("topology")

# ===== OID 定义 =====
# LLDP MIB（IEEE 802.1AB）
LLDP_CHASSIS_ID = "1.0.8802.1.1.2.1.1.1"
LLDP_PORT_ID = "1.0.8802.1.1.2.1.1.2"
LLDP_PORT_DESC = "1.0.8802.1.1.2.1.1.3"
LLDP_SYS_NAME = "1.0.8802.1.1.2.1.1.4"
LLDP_SYS_DESC = "1.0.8802.1.1.2.1.1.5"
LLDP_REMOTE_CHASSIS_ID = "1.0.8802.1.1.2.1.4.1.1.4"
LLDP_REMOTE_PORT_ID = "1.0.8802.1.1.2.1.4.1.1.7"
LLDP_REMOTE_SYS_NAME = "1.0.8802.1.1.2.1.4.1.1.9"

# Cisco CDP MIB
CISCO_CDP_CACHE = "1.3.6.1.4.1.9.9.23.1.2.1"

# BRIDGE-MIB
BRIDGE_DOT1D_BASE = "1.3.6.1.2.1.17.1"
BRIDGE_DOT1D_PORT = "1.3.6.1.2.1.17.4.1"

# IF-MIB
IF_DESCR = "1.3.6.1.2.1.2.2.1.2"
IF_TYPE = "1.3.6.1.2.1.2.2.1.3"
IF_SPEED = "1.3.6.1.2.1.2.2.1.5"
IF_OPER_STATUS = "1.3.6.1.2.1.2.2.1.8"

# IP-MIB（ARP 表）
IP_NET_TO_MEDIA = "1.3.6.1.2.1.4.22.1"


# ===== 设备类型/厂商推断 =====

def infer_device_type(sys_descr: str, sys_name: str = "") -> str:
    """根据 sysDescr 和 sysName 推断设备类型"""
    descr_lower = (sys_descr + " " + sys_name).lower()

    keywords_router = ["router", "ios", "routing", "bgp", "ospf"]
    keywords_switch = ["switch", "catalyst", "procurve", "icos", "stp"]
    keywords_firewall = ["fortinet", "pfsense", "firewall", "fortigate", "sonicwall"]
    keywords_ap = ["access point", "wireless", "capwap", "airo", "unifi"]
    keywords_camera = ["camera", "ipcamera", "hikvision", "dahua"]
    keywords_server = ["windows server", "linux", "vmware", "esxi", "hyper-v"]

    if any(k in descr_lower for k in keywords_router):
        return "router"
    if any(k in descr_lower for k in keywords_switch):
        return "switch"
    if any(k in descr_lower for k in keywords_firewall):
        return "firewall"
    if any(k in descr_lower for k in keywords_ap):
        return "access_point"
    if any(k in descr_lower for k in keywords_camera):
        return "camera"
    if any(k in descr_lower for k in keywords_server):
        return "server"
    return "unknown"


def infer_vendor(sys_descr: str) -> str:
    """根据 sysDescr 推断厂商"""
    d = sys_descr.lower()
    if "cisco" in d:
        return "Cisco"
    if "huawei" in d:
        return "Huawei"
    if "hp" in d or "procurve" in d:
        return "HP"
    if "arista" in d:
        return "Arista"
    if "juniper" in d:
        return "Juniper"
    if "mikrotik" in d:
        return "MikroTik"
    if "tp-link" in d or "tp link" in d:
        return "TP-Link"
    if "hikvision" in d:
        return "Hikvision"
    if "dahua" in d:
        return "Dahua"
    if "fortinet" in d:
        return "Fortinet"
    if "ubiquiti" in d or "unifi" in d:
        return "Ubiquiti"
    return "Unknown"


# ===== 核心发现逻辑 =====

class TopologyDiscoverer:
    """拓扑发现引擎，从种子设备出发逐跳发现网络拓扑"""

    def __init__(self, agent_id: str = ""):
        self.agent_id = agent_id
        self.discovered_ips: set = set()
        self.nodes: List[Dict] = []
        self.links: List[Dict] = []
        self.snmp_cache: Dict[Tuple[str, str], Tuple[bool, str]] = {}

    # --------------------------------------------------------- public API

    def discover(self, seed_ips: List[str], community: str = "public",
                 max_hops: int = 3, max_devices: int = 50) -> Dict[str, Any]:
        """从种子 IP 开始递归发现拓扑"""
        self.discovered_ips = set()
        self.nodes = []
        self.links = []

        queue: List[Tuple[str, int]] = [(ip, 0) for ip in seed_ips]

        while queue:
            ip, hop = queue.pop(0)
            if ip in self.discovered_ips or hop > max_hops:
                continue
            if len(self.discovered_ips) >= max_devices:
                break

            self.discovered_ips.add(ip)
            logger.info("发现设备 [%d/%d]: %s", hop, max_hops, ip)

            node = self._discover_node(ip, community)
            if node:
                self.nodes.append(node)

            neighbors = self._discover_neighbors(ip, community)
            for neighbor_ip, port_id in neighbors:
                self.links.append({
                    "from_ip": ip,
                    "from_port": port_id,
                    "to_ip": neighbor_ip,
                    "to_port": "",
                    "link_type": "lldp",
                })
                if neighbor_ip not in self.discovered_ips:
                    queue.append((neighbor_ip, hop + 1))

            arp_ips = self._discover_arp_neighbors(ip, community)
            known_neighbor_ips = {n[0] for n in neighbors}
            for arp_ip in arp_ips:
                if arp_ip not in self.discovered_ips and arp_ip not in known_neighbor_ips:
                    queue.append((arp_ip, hop + 1))

        return self._build_result()

    # ------------------------------------------------------ node discovery

    def _discover_node(self, ip: str, community: str) -> Optional[Dict[str, Any]]:
        node: Dict[str, Any] = {
            "ip": ip,
            "mac": "",
            "hostname": "",
            "device_type": "unknown",
            "vendor": "Unknown",
            "sys_descr": "",
            "interfaces": {},
            "last_seen": datetime.now().isoformat(),
        }

        ok, val = self._snmp_get_cached(ip, "1.3.6.1.2.1.1.1.0", community)
        if ok and val:
            node["sys_descr"] = val
            node["vendor"] = infer_vendor(val)

        ok, val = self._snmp_get_cached(ip, "1.3.6.1.2.1.1.5.0", community)
        if ok and val:
            node["hostname"] = val

        ok, val = self._snmp_get_cached(ip, "1.3.6.1.2.1.1.3.0", community)
        if ok and val:
            node["uptime"] = val

        node["device_type"] = infer_device_type(node["sys_descr"], node["hostname"])

        mac = self._get_mac_address(ip, community)
        if mac:
            node["mac"] = mac

        node["interfaces"] = self._get_interfaces(ip, community)
        return node

    # ---------------------------------------------------- neighbor discovery

    def _discover_neighbors(self, ip: str, community: str) -> List[Tuple[str, str]]:
        neighbors = self._discover_lldp_neighbors(ip, community)
        if not neighbors:
            neighbors = self._discover_cdp_neighbors(ip, community)
        return neighbors

    def _discover_lldp_neighbors(self, ip: str, community: str) -> List[Tuple[str, str]]:
        neighbors: List[Tuple[str, str]] = []

        port_rows = snmp_bulkwalk(ip, LLDP_REMOTE_PORT_ID, community, max_rows=100)
        chassis_rows = snmp_bulkwalk(ip, LLDP_REMOTE_CHASSIS_ID, community, max_rows=100)

        # Build index: port-index -> port_id
        port_map: Dict[str, str] = {}
        for oid_str, val_str in port_rows:
            try:
                idx = oid_str.rsplit(".", 1)[-1]
                port_map[idx] = val_str
            except Exception:
                pass

        for oid_str, val_str in chassis_rows:
            try:
                idx = oid_str.rsplit(".", 1)[-1]
                port_id = port_map.get(idx, "")
                neighbor_ip = self._resolve_chassis_id(val_str)
                if neighbor_ip:
                    neighbors.append((neighbor_ip, port_id))
            except Exception:
                pass

        return neighbors

    def _discover_cdp_neighbors(self, ip: str, community: str) -> List[Tuple[str, str]]:
        neighbors: List[Tuple[str, str]] = []
        try:
            rows = snmp_bulkwalk(ip, CISCO_CDP_CACHE, community, max_rows=100)
            for _oid_str, val_str in rows:
                if self._looks_like_ip(val_str):
                    neighbors.append((val_str, "cdp"))
        except Exception:
            pass
        return neighbors

    def _discover_arp_neighbors(self, ip: str, community: str) -> List[str]:
        arp_ips: List[str] = []
        try:
            rows = snmp_bulkwalk(ip, IP_NET_TO_MEDIA, community, max_rows=200)
            for oid_str, _val_str in rows:
                try:
                    parts = oid_str.rsplit(".", 4)
                    if len(parts) >= 4:
                        ip_str = ".".join(parts[-4:])
                        if self._looks_like_ip(ip_str) and ip_str != ip:
                            arp_ips.append(ip_str)
                except Exception:
                    pass
        except Exception:
            pass
        return list(set(arp_ips))

    # ----------------------------------------------------------- helpers

    def _resolve_chassis_id(self, chassis_id: str) -> Optional[str]:
        if self._looks_like_ip(chassis_id):
            return chassis_id
        if self._looks_like_mac(chassis_id):
            return None
        return None

    @staticmethod
    def _looks_like_ip(s: str) -> bool:
        parts = s.split(".")
        if len(parts) != 4:
            return False
        try:
            return all(0 <= int(p) <= 255 for p in parts)
        except ValueError:
            return False

    @staticmethod
    def _looks_like_mac(s: str) -> bool:
        s = s.replace(":", "").replace("-", "").replace(".", "")
        if len(s) != 12:
            return False
        try:
            int(s, 16)
            return True
        except ValueError:
            return False

    def _get_mac_address(self, ip: str, community: str) -> Optional[str]:
        try:
            rows = snmp_bulkwalk(ip, IP_NET_TO_MEDIA, community, max_rows=50)
            for _oid_str, val_str in rows:
                if self._looks_like_mac(val_str):
                    return val_str.upper()
        except Exception:
            pass
        try:
            rows = snmp_bulkwalk(ip, LLDP_CHASSIS_ID, community, max_rows=20)
            for _oid_str, val_str in rows:
                if self._looks_like_mac(val_str):
                    return val_str.upper()
        except Exception:
            pass
        return None

    def _get_interfaces(self, ip: str, community: str) -> Dict[int, Dict]:
        interfaces: Dict[int, Dict] = {}
        try:
            rows = snmp_bulkwalk(ip, IF_DESCR, community, max_rows=100)
            for oid_str, val_str in rows:
                try:
                    idx = int(oid_str.rsplit(".", 1)[-1])
                    interfaces[idx] = {"descr": val_str, "status": "unknown"}
                except Exception:
                    pass
        except Exception:
            pass
        try:
            rows = snmp_bulkwalk(ip, IF_OPER_STATUS, community, max_rows=100)
            for oid_str, val_str in rows:
                try:
                    idx = int(oid_str.rsplit(".", 1)[-1])
                    if idx in interfaces:
                        status_map = {"1": "up", "2": "down", "3": "testing", "4": "unknown"}
                        interfaces[idx]["status"] = status_map.get(val_str, "unknown")
                except Exception:
                    pass
        except Exception:
            pass
        return interfaces

    def _snmp_get_cached(self, ip: str, oid: str, community: str) -> Tuple[bool, str]:
        key = (ip, oid)
        if key in self.snmp_cache:
            return self.snmp_cache[key]
        ok, val = snmp_get(ip, oid, community)
        self.snmp_cache[key] = (ok, val)
        return ok, val

    def _build_result(self) -> Dict[str, Any]:
        return {
            "nodes": self.nodes,
            "links": self.links,
            "discovered_count": len(self.nodes),
            "link_count": len(self.links),
            "agent_id": self.agent_id,
            "discovered_at": datetime.now().isoformat(),
        }


class TopologyManager:
    """拓扑管理器：持久化和查询拓扑数据"""

    _instance: Optional["TopologyManager"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    # ----------------------------------------------------------- persistence

    @staticmethod
    def save_topology(agent_id: str, nodes: List[Dict], links: List[Dict]):
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

    @staticmethod
    def discover_and_save(agent_id: str, seed_ips: List[str],
                          community: str = "public") -> Dict[str, Any]:
        """一键发现 + 保存"""
        discoverer = TopologyDiscoverer(agent_id)
        result = discoverer.discover(seed_ips, community)
        TopologyManager.save_topology(agent_id, result["nodes"], result["links"])
        return result


topology_manager = TopologyManager()
