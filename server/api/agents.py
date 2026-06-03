import secrets
import logging
import io
import json

logger = logging.getLogger("agents")
from datetime import datetime, timezone
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
            return {"success": True, "message": "设备已重新注册", "agent_id": existing["agent_id"], "token": existing["token"], "interval": payload.get("interval", config.AGENT_DEFAULT_INTERVAL)}
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
async def get_agents():
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
                    except Exception as e:
                        logger.warning("解析企业 ping 时间戳失败: %s", e)

            # 查询关联的 SNMP 设备
            snmp_devices_list = []
            dev_rows = cursor.execute(
                "SELECT ip, port, description, snmp_version, created_at FROM snmp_devices WHERE agent_id=? ORDER BY created_at DESC",
                (aid,)
            ).fetchall()
            if not dev_rows and r["ip"]:
                dev_rows = cursor.execute(
                    "SELECT ip, port, description, snmp_version, created_at FROM snmp_devices WHERE agent_id='admin' AND ip=? ORDER BY created_at DESC",
                    (r["ip"],)
                ).fetchall()
            for dev in dev_rows:
                dd = dict(dev)
                # 最新指标时间
                ts_row = cursor.execute(
                    "SELECT timestamp FROM snmp_metrics WHERE device_ip=? ORDER BY timestamp DESC LIMIT 1",
                    (dd["ip"],)
                ).fetchone()
                online = False
                if ts_row and ts_row["timestamp"]:
                    try:
                        last_dt = datetime.fromisoformat(ts_row["timestamp"])
                        online = (datetime.now(timezone.utc) - last_dt).total_seconds() < 600
                    except Exception as e:
                        logger.warning("解析 SNMP 设备时间戳失败: %s", e)
                # 提取 CPU 和运行时间指标
                metrics_rows = cursor.execute(
                    "SELECT oid, value FROM snmp_metrics WHERE device_ip=? ORDER BY timestamp DESC LIMIT 200",
                    (dd["ip"],)
                ).fetchall()
                cpu = None
                uptime = None
                seen = set()
                for m in metrics_rows:
                    oid = m["oid"]
                    if oid in seen:
                        continue
                    seen.add(oid)
                    val = m["value"]
                    if oid.startswith("1.3.6.1.2.1.25.3.3.1.2") or oid == "1.3.6.1.4.1.9.2.1.57.0":
                        cpu = val
                    elif oid == "1.3.6.1.2.1.1.3.0":
                        uptime = val
                snmp_devices_list.append({
                    "ip": dd["ip"],
                    "name": dd.get("description") or f"SNMP-{dd['ip']}",
                    "online": online,
                    "cpu": cpu,
                    "uptime": uptime,
                    "version": dd.get("snmp_version", "2c"),
                })

            # 上线方式：仅 Windows 客户端、被动 Ping、Linux 客户端
            methods = []
            os_type = (r["os_type"] or "").lower()
            if _is_recent(r["last_seen"]) or os_type:
                if os_type == "windows":
                    methods.append("Windows 客户端")
                elif os_type == "linux":
                    methods.append("Linux 客户端")
                else:
                    methods.append("客户端")
            # 被动 Ping
            if ping_status is not None:
                methods.append("被动 Ping")

            # 综合判定在线状态：agent 上报 / Ping 探测
            is_online = _is_recent(r["last_seen"])
            if not is_online and ping_status and ping_status.get("status") == "online":
                is_online = True

            has_agent = bool(methods and "客户端" in methods[0])
            has_ping = ping_status is not None

            # 查询最近 5 条诊断报告
            diag_rows = cursor.execute(
                "SELECT id, report_json, created_at FROM diag_reports WHERE agent_id=? ORDER BY created_at DESC LIMIT 5",
                (aid,)
            ).fetchall()
            diag_reports = [
                {"id": d["id"], "report": json.loads(d["report_json"]), "created_at": d["created_at"]}
                for d in diag_rows
            ]

            result.append({
                "agent_id": aid,
                "name": r["name"] or "",
                "ip": r["ip"] or "",
                "ip_type": _classify_ip(r["ip"]),
                "last_seen": r["last_seen"],
                "online": is_online,
                "device_count": device_count,
                "alert_24h": alert_count,
                "ping": ping_status,
                "snmp_devices": snmp_devices_list,
                "methods": methods,
                "has_agent": has_agent,
                "has_ping": has_ping,
                "diag_reports": diag_reports,
            })
        return result


@router.post("/{agent_id}/diag")
async def report_diag(agent_id: str, payload: dict):
    """存储客户端断线诊断报告"""
    with get_db() as conn:
        cursor = conn.cursor()
        # 验证 agent 存在
        cursor.execute("SELECT agent_id FROM agents WHERE agent_id = ?", (agent_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="设备不存在")
        cursor.execute(
            "INSERT INTO diag_reports (agent_id, report_json) VALUES (?, ?)",
            (agent_id, json.dumps(payload)))
    return {"success": True}


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


def _classify_ip(ip: str) -> str:
    """判断 IP 类型：public / private / none"""
    if not ip:
        return "none"
    try:
        parts = list(map(int, ip.split(".")))
        if len(parts) != 4:
            return "none"
        if parts[0] == 10:
            return "private"
        if parts[0] == 172 and 16 <= parts[1] <= 31:
            return "private"
        if parts[0] == 192 and parts[1] == 168:
            return "private"
        if parts[0] == 127:
            return "none"
        if parts[0] == 169 and parts[1] == 254:
            return "none"
        return "public"
    except (ValueError, IndexError) as e:
        logger.warning("IP 分类异常 [%s]: %s", ip, e)
        return "none"


def _is_recent(last_seen: Optional[str], seconds: int = 120) -> bool:
    if not last_seen:
        return False
    from datetime import datetime, timedelta, timezone
    try:
        last = datetime.fromisoformat(last_seen + "+00:00")
        return datetime.now(timezone.utc) - last < timedelta(seconds=seconds)
    except Exception as e:
        logger.warning("解析 last_seen 时间失败 [%s]: %s", last_seen, e)
        return False
