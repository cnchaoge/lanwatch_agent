from fastapi import APIRouter, HTTPException, Header, Body
from typing import Optional, List, Dict, Any
from datetime import datetime
import json
from core.database import get_db
from core.auth import verify_agent_token
from modules.ping import ping_host

router = APIRouter()


@router.post("/{agent_id}/report")
async def report(agent_id: str, body: Any = Body(...), authorization: Optional[str] = Header(None)):
    verified_id = verify_agent_token(authorization)
    if verified_id != agent_id:
        raise HTTPException(status_code=403, detail="token 与 agent_id 不匹配")
    # 客户端发单个 dict 或 {{"reports": [{{...}}]}} 或纯列表，统一处理
    if isinstance(body, dict):
        items = body.get("reports", [body])
    elif isinstance(body, list):
        items = body
    else:
        items = [body]
    with get_db() as conn:
        cursor = conn.cursor()
        for r in items:
            cursor.execute("INSERT INTO probe_results (agent_id, probe_type, target, status, rtt_ms, raw_output) VALUES (?, ?, ?, ?, ?, ?)",
                (agent_id, r.get("probe_type"), r.get("target"), r.get("status"), r.get("rtt_ms"), json.dumps(r, ensure_ascii=False) if r else None))
        cursor.execute("UPDATE agents SET last_seen = ? WHERE agent_id = ?", (datetime.now().isoformat(), agent_id))
    return {"success": True, "received": len(items)}


@router.post("/{agent_id}/topology")
async def report_topology(agent_id: str, body: Any = Body(...), authorization: Optional[str] = Header(None)):
    verified_id = verify_agent_token(authorization)
    if verified_id != agent_id:
        raise HTTPException(status_code=403, detail="token 与 agent_id 不匹配")
    # 客户端发 {"devices": [...]}，服务端也直接支持 {"nodes": [...]} 或 {"devices": [...]} 或纯列表
    if isinstance(body, dict):
        nodes = body.get("nodes", body.get("devices", []))
        links = body.get("links", [])
    elif isinstance(body, list):
        nodes = body
        links = []
    else:
        nodes = []
        links = []
    with get_db() as conn:
        cursor = conn.cursor()
        for node in nodes:
            cursor.execute("INSERT OR REPLACE INTO topology_nodes (agent_id, ip, mac, hostname, device_type, vendor, raw_data, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (agent_id, node.get("ip",""), node.get("mac",""), node.get("hostname",""), node.get("device_type","unknown"), node.get("vendor",""), str(node.get("raw_data","")), datetime.now().isoformat()))
        for link in links:
            cursor.execute("INSERT OR REPLACE INTO topology_links (node_a_ip, node_a_port, node_b_ip, node_b_port, link_type) VALUES (?, ?, ?, ?, ?)",
                (link.get("from",""), link.get("from_port",""), link.get("to",""), link.get("to_port",""), link.get("type","ethernet")))
    return {"success": True, "nodes": len(nodes), "links": len(links)}


@router.post("/{agent_id}/offline")
async def report_offline(agent_id: str, authorization: Optional[str] = Header(None)):
    """客户端下线通知"""
    verified_id = verify_agent_token(authorization)
    if verified_id != agent_id:
        raise HTTPException(status_code=403, detail="token 与 agent_id 不匹配")
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE agents SET last_seen = ? WHERE agent_id = ?", (datetime.now().isoformat(), agent_id))
    return {"success": True}


@router.post("/{agent_id}/uninstall")
async def report_uninstall(agent_id: str, authorization: Optional[str] = Header(None)):
    """客户端卸载通知（删除 agent 及关联数据）"""
    verified_id = verify_agent_token(authorization)
    if verified_id != agent_id:
        raise HTTPException(status_code=403, detail="token 与 agent_id 不匹配")
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM agents WHERE agent_id = ?", (agent_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="设备不存在")
    return {"success": True, "message": f"Agent {agent_id} 已卸载"}


@router.post("/{agent_id}/diag")
async def receive_diag(agent_id: str, report_data: Dict[str, Any] = Body(...), authorization: Optional[str] = Header(None)):
    verified_id = verify_agent_token(authorization)
    if verified_id != agent_id:
        raise HTTPException(status_code=403, detail="token 与 agent_id 不匹配")
    import json
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO diag_reports (agent_id, report_json) VALUES (?, ?)", (agent_id, json.dumps(report_data, ensure_ascii=False)))
    return {"success": True}


@router.get("/device/{agent_id}")
async def get_device_status(agent_id: str):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM agents WHERE agent_id = ?", (agent_id,))
        agent = cursor.fetchone()
        if not agent:
            raise HTTPException(status_code=404, detail="设备不存在")
        cursor.execute("SELECT * FROM probe_results WHERE agent_id = ? ORDER BY created_at DESC LIMIT 20", (agent_id,))
        probes = [dict(r) for r in cursor.fetchall()]
        return {"agent": dict(agent), "recent_probes": probes}


@router.get("/snmp_devices/{agent_id}")
async def get_snmp_devices(agent_id: str):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM snmp_devices WHERE agent_id = ?", (agent_id,))
        return [dict(r) for r in cursor.fetchall()]


@router.get("/snmp_metrics/{device_ip}")
async def get_snmp_metrics(device_ip: str, limit: int = 100):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM snmp_metrics WHERE device_ip = ? ORDER BY timestamp DESC LIMIT ?", (device_ip, limit))
        return [dict(r) for r in cursor.fetchall()]
