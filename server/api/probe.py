from fastapi import APIRouter, HTTPException, Header, Body, Request
from typing import Optional, List, Dict, Any
from datetime import datetime
import json
from core.database import get_db
from core.auth import verify_agent_token
from modules.ping import ping_host

router = APIRouter()


_NUMERIC_METRICS = {
    "ping_rtt_ms", "ping_loss_pct", "dns_ms", "dns_ms_ali",
    "dns_ms_tencent", "dns_ms_163", "target_rtt_ms",
    "gateway_reachable", "target_reachable",
}


def _write_agent_metrics(cursor, agent_id: str, data: dict):
    """将扁平指标写入 agent_metrics 键值表"""
    now = datetime.now().isoformat()
    for key in _NUMERIC_METRICS:
        val = data.get(key)
        if val is not None:
            try:
                cursor.execute(
                    "INSERT INTO agent_metrics (agent_id, metric_key, metric_value, created_at) VALUES (?, ?, ?, ?)",
                    (agent_id, key, float(val), now)
                )
            except (TypeError, ValueError):
                pass


@router.post("/{agent_id}/report")
async def report(agent_id: str, body: Any = Body(...), authorization: Optional[str] = Header(None), request: Request = None):
    verified_id = verify_agent_token(authorization)
    if verified_id != agent_id:
        raise HTTPException(status_code=403, detail="token 与 agent_id 不匹配")
    # 客户端发单个 dict 或 {"reports": [...]} 或纯列表，统一处理
    if isinstance(body, dict):
        items = body.get("reports", [body])
    elif isinstance(body, list):
        items = body
    else:
        items = [body]
    with get_db() as conn:
        cursor = conn.cursor()
        for r in items:
            # 兼容 Windows 客户端发送的扁平 metrics dict（不含 probe_type）
            if isinstance(r, dict) and "probe_type" not in r and "target" not in r:
                cursor.execute("INSERT INTO probe_results (agent_id, probe_type, target, status, rtt_ms, raw_output) VALUES (?, ?, ?, ?, ?, ?)",
                    (agent_id, "metrics", "all", "ok", r.get("ping_rtt_ms"), json.dumps(r, ensure_ascii=False)))
                # 同时写入 agent_metrics 键值表，支持趋势查询
                _write_agent_metrics(cursor, agent_id, r)
            else:
                cursor.execute("INSERT INTO probe_results (agent_id, probe_type, target, status, rtt_ms, raw_output) VALUES (?, ?, ?, ?, ?, ?)",
                    (agent_id, r.get("probe_type"), r.get("target"), r.get("status"), r.get("rtt_ms"), json.dumps(r, ensure_ascii=False) if r else None))
        client_ip = ""
        if request:
            client_ip = (request.headers.get("x-forwarded-for","").split(",")[0].strip() or (request.client.host if request.client else ""))
        cursor.execute("UPDATE agents SET last_seen = ?, ip = COALESCE(NULLIF(ip,''), ?) WHERE agent_id = ?", (datetime.now().isoformat(), client_ip, agent_id))
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
async def report_offline(agent_id: str, authorization: Optional[str] = Header(None), request: Request = None):
    """客户端下线通知"""
    verified_id = verify_agent_token(authorization)
    if verified_id != agent_id:
        raise HTTPException(status_code=403, detail="token 与 agent_id 不匹配")
    with get_db() as conn:
        cursor = conn.cursor()
        client_ip = ""
        if request:
            client_ip = (request.headers.get("x-forwarded-for","").split(",")[0].strip() or (request.client.host if request.client else ""))
        cursor.execute("UPDATE agents SET last_seen = ?, ip = COALESCE(NULLIF(ip,''), ?) WHERE agent_id = ?", (datetime.now().isoformat(), client_ip, agent_id))
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


@router.get("/{agent_id}/latest")
async def get_latest_metrics(agent_id: str):
    """获取 agent 最新一次上报的完整指标（解析 raw_output JSON）"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM probe_results WHERE agent_id = ? ORDER BY created_at DESC LIMIT 1",
            (agent_id,)
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="无数据")
        result = dict(row)
        # 尝试解析 raw_output JSON 合并到返回结果
        if result.get("raw_output"):
            try:
                metrics = json.loads(result["raw_output"])
                result.update(metrics)
            except (json.JSONDecodeError, TypeError):
                pass
        # 确保有 timestamp 字段
        if result.get("created_at"):
            from datetime import datetime
            try:
                ts = datetime.fromisoformat(result["created_at"] + "+00:00").timestamp()
                result["timestamp"] = ts
            except Exception:
                result["timestamp"] = 0
        return result


@router.get("/{agent_id}")
async def get_agent_info(agent_id: str):
    """获取 agent 基本信息"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM agents WHERE agent_id = ?", (agent_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="设备不存在")
        return dict(row)


@router.get("/{agent_id}/metrics/history")
async def get_agent_metrics_history(agent_id: str, metric_key: str = None, hours: int = 24):
    """查询 agent 指标历史趋势（按 metric_key 过滤，默认返回全部）"""
    with get_db() as conn:
        cursor = conn.cursor()
        if metric_key:
            cursor.execute(
                "SELECT metric_key, metric_value, created_at FROM agent_metrics "
                "WHERE agent_id = ? AND metric_key = ? AND created_at >= datetime('now', ?)"
                "ORDER BY created_at ASC",
                (agent_id, metric_key, f"-{hours} hours")
            )
        else:
            cursor.execute(
                "SELECT metric_key, metric_value, created_at FROM agent_metrics "
                "WHERE agent_id = ? AND created_at >= datetime('now', ?)"
                "ORDER BY metric_key, created_at ASC",
                (agent_id, f"-{hours} hours")
            )
        rows = cursor.fetchall()
        # 按 metric_key 分组
        result = {}
        for r in rows:
            key = r["metric_key"]
            if key not in result:
                result[key] = []
            result[key].append({
                "value": r["metric_value"],
                "ts": r["created_at"],
            })
        return result


@router.get("/{agent_id}/history")
async def get_agent_history(agent_id: str, limit: int = 60):
    """获取 agent 历史数据列表（解析 raw_output 返回，兼容前端图表）"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT raw_output, created_at FROM probe_results "
            "WHERE agent_id = ? AND raw_output IS NOT NULL "
            "ORDER BY created_at DESC LIMIT ?",
            (agent_id, limit)
        )
        rows = cursor.fetchall()
        result = []
        for r in rows:
            try:
                metrics = json.loads(r["raw_output"])
            except (json.JSONDecodeError, TypeError):
                continue
            # 添加 timestamp
            try:
                ts = datetime.fromisoformat(r["created_at"] + "+00:00").timestamp()
            except Exception:
                ts = 0
            metrics["timestamp"] = ts
            result.append(metrics)
        return result  # 按时间倒序（前端会 .reverse()）


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
