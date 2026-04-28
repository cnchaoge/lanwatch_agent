from pysnmp.hlapi.asyncio.sync.cmdgen import getCmd, bulkCmd
from pysnmp.hlapi.asyncio import SnmpEngine, CommunityData, UdpTransportTarget, ContextData, ObjectType, ObjectIdentity
from typing import List, Tuple


def snmp_get(target_ip: str, oid: str, community: str = "public", timeout: int = 5, retries: int = 3, port: int = 161) -> Tuple[bool, str]:
    iterator = getCmd(SnmpEngine(), CommunityData(community, mpModel=1), UdpTransportTarget((target_ip, port), timeout=timeout, retries=retries), ContextData(), ObjectType(ObjectIdentity(oid)))
    error_indication, error_status, error_index, var_binds = next(iterator)
    if error_indication:
        return False, str(error_indication)
    if error_status:
        return False, f"{error_status.prettyPrint()} at {error_index}"
    if var_binds:
        return True, var_binds[0][1].prettyPrint()
    return False, "no data"


def snmp_bulkwalk(target_ip: str, base_oid: str, community: str = "public", timeout: int = 5, retries: int = 3, port: int = 161, max_rows: int = 100) -> List[Tuple[str, str]]:
    results = []
    iterator = bulkCmd(SnmpEngine(), CommunityData(community, mpModel=1), UdpTransportTarget((target_ip, port), timeout=timeout, retries=retries), ContextData(), 0, max_rows, ObjectType(ObjectIdentity(base_oid)))
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
