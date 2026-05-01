"""管理后台 API：企业列表、SNMP 管理等"""
import secrets
from fastapi import APIRouter, HTTPException
from typing import Optional
from core.database import get_db
from core.config import config

router = APIRouter()


def _verify_admin(payload: dict = None, password: str = None):
    pw = password or (payload or {}).get("password", "")
    if pw != config.ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="密码错误")


@router.post("/admin/login")
async def admin_login(payload: dict):
    password = payload.get("password", "")
    if password == config.ADMIN_PASSWORD:
        return {"success": True, "message": "登录成功"}
    raise HTTPException(status_code=401, detail="密码错误")


# ── 企业（= agents 表）管理 ─────────────────────────────────────────


@router.get("/admin/users")
async def admin_get_users():
    """返回所有企业（agent），含拓扑节点作为设备列表"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT agent_id, name, token, ip, os_type, last_seen FROM agents ORDER BY created_at DESC"
        )
        rows = cursor.fetchall()
        result = []
        for r in rows:
            aid = r["agent_id"]
            # 把拓扑节点作为该企业下的设备
            cursor.execute(
                "SELECT id, ip, hostname, device_type, last_seen FROM topology_nodes WHERE agent_id = ? ORDER BY last_seen DESC",
                (aid,),
            )
            devices = []
            for d in cursor.fetchall():
                d = dict(d)
                devices.append({
                    "id": str(d["id"]),
                    "agent_id": aid,
                    "name": d.get("hostname") or d.get("ip", ""),
                    "ip": d.get("ip", ""),
                    "device_type": d.get("device_type", ""),
                    "last_seen": d.get("last_seen"),
                })
            result.append({
                "id": aid,
                "name": r["name"] or "",
                "phone": "",
                "token": r["token"],
                "agents": devices,
                "ip": r["ip"] or "",
                "os_type": r["os_type"] or "",
                "last_seen": r["last_seen"],
            })
        return result


@router.post("/admin/users")
async def admin_create_user(payload: dict):
    """手动创建企业"""
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="企业名称不能为空")
    phone = (payload.get("phone") or "").strip()
    agent_id = secrets.token_hex(16)
    token = secrets.token_hex(32)
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO agents (agent_id, name, token) VALUES (?, ?, ?)",
            (agent_id, name, token),
        )
    return {"success": True, "agent_id": agent_id, "token": token}


@router.patch("/admin/users/{user_id}")
async def admin_update_user(user_id: str, payload: dict):
    name = (payload.get("name") or "").strip()
    with get_db() as conn:
        cursor = conn.cursor()
        if name:
            cursor.execute("UPDATE agents SET name = ? WHERE agent_id = ?", (name, user_id))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="企业不存在")
    return {"success": True}


@router.post("/admin/users/{user_id}/reset-token")
async def admin_reset_token(user_id: str):
    token = secrets.token_hex(32)
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE agents SET token = ? WHERE agent_id = ?", (token, user_id))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="企业不存在")
    return {"token": token}


@router.delete("/admin/users/{user_id}")
async def admin_delete_user(user_id: str):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM topology_nodes WHERE agent_id = ?", (user_id,))
        # topology_links 表无 agent_id 字段，跳过
        cursor.execute("DELETE FROM probe_results WHERE agent_id = ?", (user_id,))
        cursor.execute("DELETE FROM alert_log WHERE agent_id = ?", (user_id,))
        cursor.execute("DELETE FROM agents WHERE agent_id = ?", (user_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="企业不存在")
    return {"success": True}


# ── 设备（= topology_nodes）管理 ────────────────────────────────────


@router.patch("/admin/agents/{agent_id}")
async def admin_update_agent(agent_id: str, payload: dict):
    """更新拓扑节点信息"""
    name = (payload.get("name") or "").strip()
    with get_db() as conn:
        cursor = conn.cursor()
        if name:
            cursor.execute(
                "UPDATE topology_nodes SET hostname = ? WHERE id = ?",
                (name, agent_id),
            )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="设备不存在")
    return {"success": True}


@router.delete("/admin/agents/{agent_id}")
async def admin_delete_agent(agent_id: str):
    """删除拓扑节点"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM topology_nodes WHERE id = ?", (agent_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="设备不存在")
    return {"success": True}


# ── SNMP 设备管理 ────────────────────────────────────────────────────


@router.get("/admin/snmp")
async def admin_get_snmp():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, agent_id, ip, community, device_name, device_type, snmp_version, status, last_poll FROM snmp_devices ORDER BY device_name"
        )
        rows = cursor.fetchall()
        return [
            {
                "id": r["id"],
                "agent_id": r["agent_id"],
                "ip": r["ip"],
                "community": r["community"],
                "device_name": r["device_name"] or "",
                "device_type": r["device_type"] or "unknown",
                "snmp_version": r["snmp_version"] or "2c",
                "status": r["status"] or "unknown",
                "last_poll": r["last_poll"],
            }
            for r in rows
        ]


@router.post("/admin/snmp")
async def admin_create_snmp(payload: dict):
    ip = (payload.get("ip") or "").strip()
    if not ip:
        raise HTTPException(status_code=400, detail="IP 地址不能为空")
    agent_id = payload.get("agent_id", "admin")
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO snmp_devices (agent_id, ip, community, device_name, device_type) VALUES (?, ?, ?, ?, ?)",
            (agent_id, ip, payload.get("community", "public"), payload.get("device_name", ""), payload.get("device_type", "router")),
        )
    # 创建调度任务让设备能被定时轮询
    from modules.scheduler import scheduler
    from core.config import config
    scheduler.add_probe_job(agent_id=agent_id, probe_type="ping", target=ip, interval_seconds=config.AGENT_DEFAULT_INTERVAL)
    scheduler.add_probe_job(agent_id=agent_id, probe_type="snmp", target=ip, interval_seconds=max(config.AGENT_DEFAULT_INTERVAL * 5, 300))
    return {"success": True}


@router.patch("/admin/snmp/{device_id}")
async def admin_update_snmp(device_id: int, payload: dict):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE snmp_devices SET ip=?, community=?, device_name=?, device_type=? WHERE id=?",
            (
                payload.get("ip", ""),
                payload.get("community", "public"),
                payload.get("device_name", ""),
                payload.get("device_type", "router"),
                device_id,
            ),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="SNMP 设备不存在")
    return {"success": True}


@router.delete("/admin/snmp/{device_id}")
async def admin_delete_snmp(device_id: int):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM snmp_devices WHERE id = ?", (device_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="SNMP 设备不存在")
    return {"success": True}


@router.post("/admin/snmp/{device_id}/poll")
async def admin_poll_snmp(device_id: int):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT ip, community, agent_id FROM snmp_devices WHERE id = ?", (device_id,))
        dev = cursor.fetchone()
        if not dev:
            raise HTTPException(status_code=404, detail="SNMP 设备不存在")
    from modules.snmp_manager import snmp_manager
    result = snmp_manager.collect_snmp_metrics(dev["agent_id"], dev["ip"])
    return {"status": "ok", "message": "轮询完成", "data": result}
