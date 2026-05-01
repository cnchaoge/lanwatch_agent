import secrets
import io
from fastapi import APIRouter, HTTPException, Header, Query
from fastapi.responses import Response
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
    company_name = (payload.get("name") or "").strip()
    if not company_name:
        raise HTTPException(status_code=400, detail="企业名称不能为空")
    with get_db() as conn:
        cursor = conn.cursor()
        # 按企业名称查重（每个企业对应一个唯一的 agent）
        cursor.execute("SELECT agent_id, token FROM agents WHERE name = ?", (company_name,))
        existing = cursor.fetchone()
        if existing:
            raise HTTPException(status_code=409, detail=f"企业「{company_name}」已注册，请勿重复注册")
        # agent_id 查重（存量兼容）
        cursor.execute("SELECT token FROM agents WHERE agent_id = ?", (agent_id,))
        existing_by_id = cursor.fetchone()
        if existing_by_id:
            return {"success": True, "message": "设备已注册", "agent_id": agent_id, "token": existing_by_id["token"], "interval": payload.get("interval", config.AGENT_DEFAULT_INTERVAL)}
        token = _generate_token()
        cursor.execute("INSERT INTO agents (agent_id, name, ip, os_type, token, interval) VALUES (?, ?, ?, ?, ?, ?)",
            (agent_id, company_name, payload.get("ip",""), payload.get("os_type",""), token, payload.get("interval", config.AGENT_DEFAULT_INTERVAL)))
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


@router.get("/enterprises")
async def get_enterprises():
    """返回所有企业列表（含设备数、告警数、连通性监控状态）"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT agent_id, name, ip, os_type, interval, last_seen, created_at FROM agents ORDER BY created_at DESC")
        rows = cursor.fetchall()
        result = []
        for r in rows:
            aid = r["agent_id"]
            device_count = cursor.execute(
                "SELECT COUNT(*) FROM topology_nodes WHERE agent_id = ?", (aid,)
            ).fetchone()[0]
            alert_count = cursor.execute(
                "SELECT COUNT(*) FROM alert_log WHERE agent_id = ? AND created_at >= datetime('now', '-24 hours')", (aid,)
            ).fetchone()[0]
            # 查询 ping 状态（优先 agent_id 匹配，再按 IP 匹配）
            ping_status = None
            ping_row = cursor.execute(
                """SELECT pr.status as last_status, pr.rtt_ms as last_rtt,
                          pr.created_at as last_check
                   FROM scheduler_jobs sj
                   LEFT JOIN (
                       SELECT target, status, rtt_ms, created_at,
                              ROW_NUMBER() OVER (PARTITION BY target ORDER BY created_at DESC) rn
                       FROM probe_results WHERE probe_type='ping'
                   ) pr ON sj.target = pr.target AND pr.rn = 1
                   WHERE sj.probe_type='ping'
                     AND (sj.agent_id=? OR (sj.agent_id='admin' AND sj.target=?))
                   ORDER BY CASE WHEN sj.agent_id=? THEN 0 ELSE 1 END
                   LIMIT 1""",
                (aid, r["ip"], aid),
            ).fetchone()
            if ping_row:
                pr = dict(ping_row)
                ping_status = {
                    "status": "online" if pr.get("last_status") == "ok" else "offline",
                    "rtt_ms": pr.get("last_rtt"),
                }
                if pr.get("last_check"):
                    try:
                        ping_status["last_seen"] = datetime.fromisoformat(pr["last_check"] + "+00:00").timestamp()
                    except Exception:
                        pass

            # 查询上线方式
            methods = []
            # 1. Agent 客户端
            os_type = (r["os_type"] or "").lower()
            has_agent = _is_recent(r["last_seen"]) or bool(os_type)
            if has_agent:
                label = "Windows 客户端" if os_type == "windows" else "Linux 客户端" if os_type == "linux" else "客户端"
                methods.append(label)
            # 2. SNMP 设备
            snmp_count = cursor.execute(
                "SELECT COUNT(*) FROM snmp_devices WHERE agent_id=?",
                (aid,),
            ).fetchone()[0]
            has_snmp = snmp_count > 0
            if has_snmp:
                methods.append("SNMP 设备")
            # 3. SNMP 设备通过 IP 匹配（agent_id='admin' 但 IP 匹配）
            if not has_snmp and r["ip"]:
                snmp_admin_count = cursor.execute(
                    "SELECT COUNT(*) FROM snmp_devices WHERE agent_id='admin' AND ip=?",
                    (r["ip"],),
                ).fetchone()[0]
                if snmp_admin_count > 0:
                    methods.append("SNMP 设备")
                    has_snmp = True
            # 4. 被动 Ping
            has_ping = ping_status is not None
            if has_ping:
                methods.append("被动 Ping")

            result.append({
                "agent_id": aid,
                "name": r["name"] or "",
                "ip": r["ip"] or "",
                "last_seen": r["last_seen"],
                "online": _is_recent(r["last_seen"]),
                "device_count": device_count,
                "alert_24h": alert_count,
                "ping": ping_status,
                "methods": methods,
                "has_agent": has_agent,
                "has_snmp": has_snmp,
                "has_ping": has_ping,
            })
        return result


@router.delete("/agents/{agent_id}")
async def delete_agent(agent_id: str, password: str = Query(...)):
    verify_admin_password(password)
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM agents WHERE agent_id = ?", (agent_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="设备不存在")
        return {"success": True, "message": f"设备 {agent_id} 已删除"}


@router.get("/qr")
async def generate_qr(text: str = Query(...)):
    """生成二维码图片"""
    import qrcode
    from qrcode.image.pil import PilImage
    img = qrcode.make(text)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return Response(content=buf.getvalue(), media_type="image/png")


def _is_recent(last_seen: Optional[str], seconds: int = 120) -> bool:
    if not last_seen:
        return False
    from datetime import datetime, timedelta, timezone
    try:
        last = datetime.fromisoformat(last_seen + "+00:00")
        return datetime.now(timezone.utc) - last < timedelta(seconds=seconds)
    except Exception:
        return False
