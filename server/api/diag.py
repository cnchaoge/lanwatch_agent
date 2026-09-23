"""Diagnostic 报告上传 + 查询端点。

路由清单（挂载到 /api 前缀后）：
- POST /{agent_id}/diag              Agent / Diagnostic 工具上传报告（Bearer token 鉴权）
- GET  /diag_reports/{agent_id}      查询历史报告（X-Diagnostic-Token 鉴权）

历史变更：
- 2026-09-23  POST /{agent_id}/diag 从 api/probe.py 迁入本文件，统一 diag 相关路由；
  鉴权方式与普通 Agent 上报一致（Bearer token + agents.token 校验）。
  同时**接管**了 api/agents.py:144 的同名无鉴权路由（已 @deprecated）。
  路由生效条件：diag_router 必须在 main.py 中**先于** agents_router 注册。
- 2026-09-23  GET /diag_reports/{agent_id} 增加 X-Diagnostic-Token 鉴权，
  解决 MVP 阶段 `diagnostic` 共享 agent_id 导致报告公开可读的问题。
"""
import json
import secrets
from typing import Optional, Dict, Any

from fastapi import APIRouter, HTTPException, Header, Body, Depends

from core.config import config
from core.database import get_db
from core.auth import verify_agent_token

router = APIRouter()


def _verify_diagnostic_token(
    x_diagnostic_token: Optional[str] = Header(None, alias="X-Diagnostic-Token"),
) -> None:
    """校验 X-Diagnostic-Token：与 .env 中 DIAGNOSTIC_VIEW_TOKEN 常量时间比对。

    Fail-closed：环境变量未配置时一律拒绝（强制要求显式启用，避免新部署默认开放）。
    """
    expected = config.DIAGNOSTIC_VIEW_TOKEN
    if not expected:
        raise HTTPException(
            status_code=401,
            detail="服务端未配置 DIAGNOSTIC_VIEW_TOKEN，拒绝访问（fail-closed）",
        )
    if not x_diagnostic_token or not secrets.compare_digest(x_diagnostic_token, expected):
        raise HTTPException(status_code=401, detail="X-Diagnostic-Token 缺失或错误")


@router.post("/{agent_id}/diag")
async def receive_diag(
    agent_id: str,
    report_data: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(None),
):
    """接收 Agent / lanwatch-diagnostic 工具上报的诊断报告。

    鉴权方式与 POST /api/{agent_id}/report 一致：Authorization: Bearer <token>，
    token 必须在 agents.token 列里存在，且对应 agent_id 与 URL 一致。

    本端点接管了 server/api/agents.py:147 的同名无鉴权路由（已 @deprecated）。
    """
    verified_id = verify_agent_token(authorization)
    if verified_id != agent_id:
        raise HTTPException(status_code=403, detail="token 与 agent_id 不匹配")
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO diag_reports (agent_id, report_json) VALUES (?, ?)",
            (agent_id, json.dumps(report_data, ensure_ascii=False)),
        )
    return {"success": True}


@router.get("/diag_reports/{agent_id}")
async def get_diag_reports(
    agent_id: str,
    limit: int = 50,
    _: None = Depends(_verify_diagnostic_token),
):
    """查询指定 agent 的历史诊断报告（最新在前，最多 limit 条，默认 50）。

    鉴权：Header X-Diagnostic-Token: <DIAGNOSTIC_VIEW_TOKEN>。
    """
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM diag_reports WHERE agent_id = ? ORDER BY created_at DESC LIMIT ?",
            (agent_id, limit),
        )
        rows = cursor.fetchall()
        return [
            {
                "id": r["id"],
                "agent_id": r["agent_id"],
                "report": json.loads(r["report_json"]),
                "created_at": r["created_at"],
            }
            for r in rows
        ]