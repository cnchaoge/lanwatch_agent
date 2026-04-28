from typing import Dict, Any


def parse_trap(authenticated: bool, observer_addr: tuple) -> Dict[str, Any]:
    source_ip, source_port = observer_addr
    return {
        "source_ip": source_ip,
        "source_port": source_port,
        "trap_type": "raw",
        "note": "SNMP Trap 接收依赖原生 socket，完整 ASN.1 解析待后续接入 pysnmp"
    }
