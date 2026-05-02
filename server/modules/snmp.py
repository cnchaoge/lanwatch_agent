from pysnmp.hlapi import (
    SnmpEngine, CommunityData, UsmUserData,
    UdpTransportTarget, ContextData, ObjectType, ObjectIdentity,
    usmHMACMD5AuthProtocol, usmHMACSHAAuthProtocol,
    usmDESPrivProtocol, usmAesCfb128Protocol,
    getCmd, bulkCmd,
)
from typing import List, Tuple


_AUTH_PROTOCOLS = {
    "MD5": usmHMACMD5AuthProtocol,
    "SHA": usmHMACSHAAuthProtocol,
}
_PRIV_PROTOCOLS = {
    "DES": usmDESPrivProtocol,
    "AES": usmAesCfb128Protocol,
}


def _make_user_data(snmp_version: str, community: str = "public",
                    v3_username: str = "", v3_auth_protocol: str = "MD5",
                    v3_auth_key: str = "", v3_priv_protocol: str = "DES",
                    v3_priv_key: str = ""):
    if snmp_version == "3":
        auth_proto = _AUTH_PROTOCOLS.get(v3_auth_protocol.upper(), usmHMACMD5AuthProtocol)
        priv_proto = _PRIV_PROTOCOLS.get(v3_priv_protocol.upper(), usmDESPrivProtocol)
        return UsmUserData(v3_username or "", v3_auth_key or "", v3_priv_key or "",
                          authProtocol=auth_proto, privProtocol=priv_proto)
    return CommunityData(community, mpModel=1)


def snmp_get(target_ip: str, oid: str, community: str = "public",
             timeout: int = 5, retries: int = 3, port: int = 161,
             snmp_version: str = "2c",
             v3_username: str = "", v3_auth_protocol: str = "MD5",
             v3_auth_key: str = "", v3_priv_protocol: str = "DES",
             v3_priv_key: str = "") -> Tuple[bool, str]:
    user_data = _make_user_data(snmp_version, community,
                                v3_username, v3_auth_protocol,
                                v3_auth_key, v3_priv_protocol, v3_priv_key)

    try:
        iterator = getCmd(
            SnmpEngine(), user_data,
            UdpTransportTarget((target_ip, port), timeout=timeout, retries=retries),
            ContextData(),
            ObjectType(ObjectIdentity(oid)),
        )
        error_indication, error_status, error_index, var_binds = next(iterator)
    except Exception as exc:
        return False, str(exc)

    if error_indication:
        return False, str(error_indication)
    if error_status:
        return False, f"{error_status.prettyPrint()} at {error_index}"
    if var_binds:
        return True, var_binds[0][1].prettyPrint()
    return False, "no data"


def snmp_bulkwalk(target_ip: str, base_oid: str, community: str = "public",
                  timeout: int = 5, retries: int = 3, port: int = 161,
                  max_rows: int = 100,
                  snmp_version: str = "2c",
                  v3_username: str = "", v3_auth_protocol: str = "MD5",
                  v3_auth_key: str = "", v3_priv_protocol: str = "DES",
                  v3_priv_key: str = "") -> List[Tuple[str, str]]:
    user_data = _make_user_data(snmp_version, community,
                                v3_username, v3_auth_protocol,
                                v3_auth_key, v3_priv_protocol, v3_priv_key)

    results: List[Tuple[str, str]] = []
    try:
        iterator = bulkCmd(
            SnmpEngine(), user_data,
            UdpTransportTarget((target_ip, port), timeout=timeout, retries=retries),
            ContextData(), 0, max_rows,
            ObjectType(ObjectIdentity(base_oid)),
        )
        for error_indication, error_status, error_index, var_binds in iterator:
            if error_indication or error_status:
                break
            for var_bind in var_binds:
                # 优先用 getOid() 获取纯数字 OID，避免 prettyPrint 返回 MIB 名
                try:
                    oid_obj = var_bind[0].getOid()
                    oid_str = oid_obj.prettyPrint()
                except Exception:
                    oid_str = var_bind[0].prettyPrint()
                val_str = var_bind[1].prettyPrint()
                results.append((oid_str, val_str))
                if not oid_str.startswith(base_oid):
                    break
    except Exception:
        pass
    return results
