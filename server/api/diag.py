from fastapi import APIRouter
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
