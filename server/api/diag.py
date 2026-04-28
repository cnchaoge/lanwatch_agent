from fastapi import APIRouter, Query
from typing import Optional
from datetime import datetime, timedelta
from core.database import get_db
import json

router = APIRouter()


@router.get("/diag_reports/{agent_id}")
async def get_diag_reports(agent_id: str, limit: int = 50):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM diag_reports WHERE agent_id = ? ORDER BY created_at DESC LIMIT ?", (agent_id, limit))
        rows = cursor.fetchall()
        return [{"id": r["id"], "agent_id": r["agent_id"], "report": json.loads(r["report_json"]), "created_at": r["created_at"]} for r in rows]


@router.get("/alerts")
async def get_alerts(agent_id: Optional[str] = None, level: Optional[str] = None, hours: int = 24):
    cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
    with get_db() as conn:
        cursor = conn.cursor()
        sql = "SELECT * FROM alert_log WHERE created_at >= ?"
        params = [cutoff]
        if agent_id:
            sql += " AND agent_id = ?"
            params.append(agent_id)
        if level:
            sql += " AND level = ?"
            params.append(level)
        sql += " ORDER BY created_at DESC LIMIT 200"
        cursor.execute(sql, params)
        return [dict(r) for r in cursor.fetchall()]


@router.post("/alerts/{alert_id}/ack")
async def acknowledge_alert(alert_id: int):
    return {"success": True, "alert_id": alert_id}
