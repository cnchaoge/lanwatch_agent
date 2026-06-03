"""SNMP 设备管理 API：注册/删除/查询/采集"""
import logging
from fastapi import APIRouter, Query, HTTPException
from typing import Optional, Dict

logger = logging.getLogger("snmp_api")
from pydantic import BaseModel
from modules.snmp_manager import snmp_manager
from core.auth import verify_admin_password
from core.config import config
from core.database import get_db
from datetime import datetime, timezone

router = APIRouter()

# 前端展示用的常用 OID → 友好名映射
_OID_FRIENDLY: Dict[str, str] = {
    "1.3.6.1.2.1.1.3.0": "sysUpTime",
    "1.3.6.1.2.1.1.5.0": "sysName",
    "1.3.6.1.2.1.1.1.0": "sysDescr",
    "1.3.6.1.4.1.9.2.1.57.0": "ciscoCpu",
    "1.3.6.1.4.1.9.2.1.8.0": "ciscoMemory",
}
# 接口相关的 OID 前缀（用于匹配 ifInOctets.1, ifOutOctets.2 等）
_OID_PREFIX_MAP: Dict[str, str] = {
    "1.3.6.1.2.1.2.2.1.10": "ifInOctets",
    "1.3.6.1.2.1.2.2.1.16": "ifOutOctets",
    "1.3.6.1.2.1.2.2.1.8":  "ifOperStatus",
    "1.3.6.1.2.1.2.2.1.2":  "ifDescr",
    "1.3.6.1.2.1.25.3.3.1.2": "hrProcessorLoad",
    "1.3.6.1.2.1.25.2.3.1.6": "hrStorageUsed",
    "1.3.6.1.2.1.25.2.3.1.5": "hrStorageSize",
}


def _oid_to_friendly(oid: str) -> str:
    """将 OID 转为友好名称，优先匹配前缀"""
    if oid in _OID_FRIENDLY:
        return _OID_FRIENDLY[oid]
    for prefix, name in _OID_PREFIX_MAP.items():
        if oid.startswith(prefix):
            return name
    # 取最后一段作为 fallback
    return oid.split(".")[-1]


class SNMPDeviceRegister(BaseModel):
    agent_id: str
    ip: str
    port: Optional[int] = 161
    community: Optional[str] = "public"
    snmp_version: Optional[str] = "2c"
    description: Optional[str] = ""
    snmpv3_username: Optional[str] = ""
    snmpv3_auth_protocol: Optional[str] = "MD5"
    snmpv3_auth_key: Optional[str] = ""
    snmpv3_priv_protocol: Optional[str] = "DES"
    snmpv3_priv_key: Optional[str] = ""


class SNMPDeviceResponse(BaseModel):
    success: bool
    message: str
    agent_id: Optional[str] = None
    ip: Optional[str] = None
    port: Optional[int] = None


@router.post("/snmp/devices")
async def register_snmp_device(
    payload: SNMPDeviceRegister,
    password: Optional[str] = Query(None),
):
    """注册 SNMP 监控设备（需要管理员密码）"""
    if config.ADMIN_PASSWORD and config.ADMIN_PASSWORD != "admin":
        verify_admin_password(password)

    result = snmp_manager.register_device(
        agent_id=payload.agent_id,
        ip=payload.ip,
        port=payload.port or 161,
        community=payload.community or "public",
        snmp_version=payload.snmp_version or "2c",
        description=payload.description or "",
        snmpv3_username=payload.snmpv3_username or "",
        snmpv3_auth_protocol=payload.snmpv3_auth_protocol or "MD5",
        snmpv3_auth_key=payload.snmpv3_auth_key or "",
        snmpv3_priv_protocol=payload.snmpv3_priv_protocol or "DES",
        snmpv3_priv_key=payload.snmpv3_priv_key or "",
    )
    return SNMPDeviceResponse(**result)


@router.delete("/snmp/devices/{agent_id}/{ip}")
async def unregister_snmp_device(
    agent_id: str,
    ip: str,
    password: Optional[str] = Query(None),
):
    """取消注册 SNMP 设备"""
    if config.ADMIN_PASSWORD and config.ADMIN_PASSWORD != "admin":
        verify_admin_password(password)

    result = snmp_manager.unregister_device(agent_id, ip)
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result["message"])
    return result


@router.get("/snmp/devices/{agent_id}")
async def list_snmp_devices(agent_id: str):
    """列出指定 Agent 下的 SNMP 设备"""
    devices = snmp_manager.list_devices(agent_id)
    return {"count": len(devices), "devices": devices}


@router.post("/snmp/collect/{agent_id}/{ip}")
async def collect_snmp_metrics(agent_id: str, ip: str):
    """手动触发一次 SNMP 指标采集"""
    result = snmp_manager.collect_snmp_metrics(agent_id, ip)
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result.get("error", "采集失败"))
    return result


@router.post("/snmp/collect_all")
async def collect_all_snmp(password: Optional[str] = Query(None)):
    """采集所有 SNMP 设备（需要管理员密码）"""
    if config.ADMIN_PASSWORD and config.ADMIN_PASSWORD != "admin":
        verify_admin_password(password)

    snmp_manager.collect_all_devices()
    return {"success": True, "message": "已触发全量采集"}


@router.get("/snmp/latest")
async def get_snmp_devices_latest():
    """返回所有 SNMP 设备及最新指标（监控面板使用）"""
    from datetime import datetime, timezone
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM snmp_devices ORDER BY created_at DESC")
        devices = [dict(r) for r in cursor.fetchall()]

        result = []
        for dev in devices:
            ip = dev["ip"]
            # 取该设备最新的指标
            cursor.execute(
                "SELECT oid, value, timestamp FROM snmp_metrics WHERE device_ip = ? "
                "ORDER BY timestamp DESC LIMIT 200",
                (ip,)
            )
            rows = cursor.fetchall()
            metrics = {}
            for r in rows:
                name = _oid_to_friendly(r["oid"])
                metrics[name] = r["value"]

            # 判断在线状态：有最新指标且在 5 分钟内
            last_poll = None
            status = 0
            if rows:
                ts = rows[0]["timestamp"]
                if ts:
                    try:
                        last_dt = datetime.fromisoformat(ts + "+00:00")
                        now_utc = datetime.now(timezone.utc)
                        # 安全校验：防止未来时间戳
                        if last_dt > now_utc:
                            last_dt = now_utc
                        last_poll = last_dt.timestamp()
                        status = 1 if (now_utc - last_dt).total_seconds() < 600 else 0
                    except Exception as e:
                        logger.warning("SNMP 最新轮询时间解析失败 [%s]: %s", dev.get("ip", "?"), e)

            # 提取有用字段
            sys_descr = metrics.get("sysDescr", "")
            sys_location = metrics.get("sysLocation", "")
            if_number = metrics.get("ifNumber", "")
            if_up = metrics.get("ifUpCount", "")
            if_down = metrics.get("ifDownCount", "")
            cpu = metrics.get("hrProcessorLoad") or metrics.get("ciscoCpu") or ""

            entry = {
                "name": dev.get("device_name") or dev.get("description") or f"SNMP-{ip}",
                "ip": ip,
                "type": dev.get("snmp_version", "v2c"),
                "status": status,
                "last_poll": last_poll,
                "metrics": metrics,
                "sys_descr": sys_descr,
                "sys_location": sys_location,
                "if_number": if_number,
                "if_up": if_up,
                "if_down": if_down,
                "cpu": cpu,
            }
            result.append(entry)

        return result
