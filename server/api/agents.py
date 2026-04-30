import secrets
from fastapi import APIRouter, HTTPException, Header, Query
from typing import Optional, List
from core.database import get_db
from core.config import config
from core.auth import verify_admin_password

router = APIRouter()


def _generate_token() -> str:
    return secrets.token_hex(config.AGENT_TOKEN_LENGTH)


@router.post("/register")
async def register_agent(payload: dict):
    # 为 Windows/Linux 客户端生成 agent_id（客户端不传则自动生成）
    agent_id = payload.get("agent_id") or secrets.token_hex(16)
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, token FROM agents WHERE agent_id = ?", (agent_id,))
        existing = cursor.fetchone()
        if existing:
            return {"success": True, "message": "设备已注册", "agent_id": agent_id, "token": existing["token"], "interval": payload.get("interval", config.AGENT_DEFAULT_INTERVAL)}
        token = _generate_token()
        cursor.execute("INSERT INTO agents (agent_id, name, ip, os_type, token, interval) VALUES (?, ?, ?, ?, ?, ?)",
            (agent_id, payload.get("name",""), payload.get("ip",""), payload.get("os_type",""), token, payload.get("interval", config.AGENT_DEFAULT_INTERVAL)))
        return {"success": True, "message": "注册成功", "agent_id": agent_id, "token": token, "interval": payload.get("interval", config.AGENT_DEFAULT_INTERVAL)}


@router.get("/agents")
async def get_agents(password: str = Query(None)):
    if config.ADMIN_PASSWORD and config.ADMIN_PASSWORD != "admin":
        verify_admin_password(password)
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT agent_id, name, ip, os_type, interval, last_seen FROM agents ORDER BY created_at DESC")
        rows = cursor.fetchall()
        return [{"id": r["agent_id"], "agent_id": r["agent_id"], "name": r["name"] or "", "ip": r["ip"] or "", "os_type": r["os_type"] or "", "interval": r["interval"] or config.AGENT_DEFAULT_INTERVAL, "last_seen": r["last_seen"], "online": _is_recent(r["last_seen"])} for r in rows]


@router.delete("/agents/{agent_id}")
async def delete_agent(agent_id: str, password: str = Query(...)):
    verify_admin_password(password)
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM agents WHERE agent_id = ?", (agent_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="设备不存在")
        return {"success": True, "message": f"设备 {agent_id} 已删除"}


def _is_recent(last_seen: Optional[str], seconds: int = 120) -> bool:
    if not last_seen:
        return False
    from datetime import datetime, timedelta
    try:
        last = datetime.fromisoformat(last_seen)
        return datetime.now() - last < timedelta(seconds=seconds)
    except Exception:
        return False
