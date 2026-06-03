"""诊断 API：单目标诊断、历史批量诊断、规则查询、快速诊断"""
import ast, logging

logger = logging.getLogger("diagnosis_api")
from typing import Optional
from datetime import datetime, timedelta
from pydantic import BaseModel
import logging
from fastapi import APIRouter, Query
from core.database import get_db
from modules.diagnosis import diagnosis_engine, DIAGNOSIS_RULES

router = APIRouter()


class DiagnoseRequest(BaseModel):
    probe_type: str
    target: str
    result: dict


@router.post("/diagnosis/diagnose")
async def diagnose_target(payload: DiagnoseRequest):
    """对单个探测结果进行诊断分析"""
    diagnoses = diagnosis_engine.diagnose(
        probe_type=payload.probe_type,
        target=payload.target,
        result=payload.result,
    )
    if not diagnoses:
        return {
            "success": True,
            "has_issues": False,
            "message": "未发现异常",
            "diagnoses": [],
        }
    return {
        "success": True,
        "has_issues": True,
        "issue_count": len(diagnoses),
        "diagnoses": diagnoses,
    }


@router.post("/diagnosis/diagnose_from_history")
async def diagnose_from_history(
    agent_id: str = Query(...),
    hours: int = Query(default=24, ge=1, le=168),
):
    """基于 Agent 最近 N 小时的探测历史批量诊断"""
    diagnoses = diagnosis_engine.diagnose_from_history(agent_id, hours)
    return {
        "agent_id": agent_id,
        "hours": hours,
        "diagnosis_count": len(diagnoses),
        "diagnoses": diagnoses,
    }


@router.get("/diagnosis/rules")
async def list_diagnosis_rules():
    """列出所有诊断规则"""
    return {
        "count": len(DIAGNOSIS_RULES),
        "rules": diagnosis_engine.get_rules(),
    }


@router.get("/diagnosis/quick/{agent_id}")
async def quick_diagnosis(agent_id: str):
    """快速诊断：对指定 Agent 最新探测结果进行分析"""
    cutoff = (datetime.now() - timedelta(hours=1)).isoformat()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT * FROM probe_results
               WHERE agent_id = ? AND created_at >= ?
               ORDER BY created_at DESC""",
            (agent_id, cutoff),
        )
        rows = cursor.fetchall()

    latest: dict = {}
    for row in rows:
        if row["probe_type"] not in latest:
            latest[row["probe_type"]] = row

    diagnoses = []
    for probe_type, row in latest.items():
        try:
            result = ast.literal_eval(
                row["raw_output"]) if row["raw_output"] else {}
        except Exception:
            result = {}
        diagnoses.extend(
            diagnosis_engine.diagnose(probe_type, row["target"], result))

    return {
        "agent_id": agent_id,
        "probes_checked": len(latest),
        "issues_found": len(diagnoses),
        "diagnoses": diagnoses,
    }
