"""SNMP 设备管理 API：注册/删除/查询/采集"""
from fastapi import APIRouter, Query, HTTPException
from typing import Optional
from pydantic import BaseModel
from modules.snmp_manager import snmp_manager
from core.auth import verify_admin_password
from core.config import config

router = APIRouter()


class SNMPDeviceRegister(BaseModel):
    agent_id: str
    ip: str
    port: Optional[int] = 161
    community: Optional[str] = "public"
    snmp_version: Optional[str] = "2c"
    description: Optional[str] = ""


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
