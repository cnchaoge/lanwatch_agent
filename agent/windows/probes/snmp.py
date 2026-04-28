"""SNMP 探测模块（从原 lanwatch_agent.py 迁移）"""
from typing import Optional, Dict, List, Tuple


def snmp_get(target_ip: str, oid: str, community: str = "public", timeout: int = 5, port: int = 161) -> Tuple[bool, str]:
    try:
        from pysnmp.hlapi.asyncio.sync.cmdgen import getCmd
        from pysnmp.hlapi.asyncio import SnmpEngine, CommunityData, UdpTransportTarget, ContextData, ObjectType, ObjectIdentity
        iterator = getCmd(SnmpEngine(), CommunityData(community, mpModel=1), UdpTransportTarget((target_ip, port), timeout=timeout), ContextData(), ObjectType(ObjectIdentity(oid)))
        error_indication, error_status, error_index, var_binds = next(iterator)
        if error_indication or error_status:
            return False, str(error_indication or error_status)
        if var_binds:
            return True, var_binds[0][1].prettyPrint()
        return False, "no data"
    except Exception as e:
        return False, str(e)


def snmp_walk(target_ip: str, base_oid: str, community: str = "public", timeout: int = 5, port: int = 161, max_rows: int = 100) -> List[Tuple[str, str]]:
    try:
        from pysnmp.hlapi.asyncio.sync.cmdgen import bulkCmd
        from pysnmp.hlapi.asyncio import SnmpEngine, CommunityData, UdpTransportTarget, ContextData, ObjectType, ObjectIdentity
        results = []
        iterator = bulkCmd(SnmpEngine(), CommunityData(community, mpModel=1), UdpTransportTarget((target_ip, port), timeout=timeout), ContextData(), 0, max_rows, ObjectType(ObjectIdentity(base_oid)))
        for error_indication, error_status, error_index, var_binds in iterator:
            if error_indication or error_status:
                break
            for var_bind in var_binds:
                oid_str = var_bind[0].prettyPrint()
                val_str = var_bind[1].prettyPrint()
                results.append((oid_str, val_str))
                if not oid_str.startswith(base_oid):
                    break
        return results
    except Exception:
        return []


def snmp_get_if_stats(target_ip: str, community: str = "public") -> Optional[Dict]:
    """获取接口统计（IF-MIB）"""
    oid = "1.3.6.1.2.1.2.2.1"
    rows = snmp_walk(target_ip, oid, community)
    if not rows:
        return None
    interfaces = {}
    for oid_str, val_str in rows:
        parts = oid_str.rsplit(".", 1)
        if len(parts) == 2:
            interfaces[int(parts[1])] = val_str
    return interfaces


def snmp_results(cfg) -> List[Dict]:
    """生成 SNMP 探测报告列表（供主循环上报使用）"""
    reports = []
    snmp_devices = cfg.get("snmp_devices", [])
    for device in snmp_devices:
        ip = device.get("ip")
        community = device.get("community", "public")
        if not ip:
            continue
        ok, val = snmp_get(ip, "1.3.6.1.2.1.1.1.0", community)
        reports.append({
            "probe_type": "snmp",
            "target": ip,
            "status": "ok" if ok else "error",
            "output": {"oid": "1.3.6.1.2.1.1.1.0", "value": val}
        })
    return reports
