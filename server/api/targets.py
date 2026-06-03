"""
Targets API - 监控目标管理
GET  /api/targets              - Agent 拉取自己的监控目标
POST /api/targets              - 新增目标
GET  /api/targets/{id}         - 获取单个目标
PUT  /api/targets/{id}         - 更新目标
DELETE /api/targets/{id}       - 删除目标
GET  /api/{agent_id}/targets   - 查看指定 Agent 的所有目标（admin用）
"""
import logging
from fastapi import APIRouter, HTTPException, Query
from typing import Optional

logger = logging.getLogger("targets")
from pydantic import BaseModel
logger = logging.getLogger("targets")
from typing import Optional, List
from core.database import get_db
from core.config import config

router = APIRouter()


# ── Request/Response Models ────────────────────────────────────────

class TargetCreate(BaseModel):
    agent_id: str
    name: str = ""
    target: str
    probe_type: str  # ping / http / port / dns / snmp
    port: int = 80
    timeout: int = 5
    interval: int = 60
    enabled: bool = True


class TargetUpdate(BaseModel):
    name: Optional[str] = None
    target: Optional[str] = None
    probe_type: Optional[str] = None
    port: Optional[int] = None
    timeout: Optional[int] = None
    interval: Optional[int] = None
    enabled: Optional[bool] = None


# ── Admin 查看指定 Agent 的目标（需 admin 密码）────────────────────

@router.get("/{agent_id}/targets")
async def get_agent_targets(agent_id: str):
    """查看指定 Agent 的所有监控目标（管理后台用）"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, agent_id, name, target, probe_type, port, timeout, interval, enabled, created_at "
            "FROM targets WHERE agent_id = ? ORDER BY id DESC",
            (agent_id,)
        )
        rows = cursor.fetchall()
        return [
            {
                "id": r["id"],
                "agent_id": r["agent_id"],
                "name": r["name"] or "",
                "target": r["target"],
                "probe_type": r["probe_type"],
                "port": r["port"],
                "timeout": r["timeout"],
                "interval": r["interval"],
                "enabled": bool(r["enabled"]),
                "created_at": r["created_at"],
            }
            for r in rows
        ]


# ── Agent 拉取配置（无认证简化版，用于 Agent 启动时拉取）────────────

@router.get("/targets")
async def get_targets(
    agent_id: str = Query(...),
    token: str = Query(...),
):
    """
    Agent 启动时调用，验证 token 后返回该 Agent 的监控目标列表。
    无需 admin 密码，Agent 凭 agent_id + token 拉取。
    """
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT token FROM agents WHERE agent_id = ?", (agent_id,))
        row = cursor.fetchone()
        if not row or row["token"] != token:
            raise HTTPException(status_code=401, detail="认证失败")

        cursor.execute(
            "SELECT id, agent_id, name, target, probe_type, port, timeout, interval, enabled "
            "FROM targets WHERE agent_id = ? AND enabled = 1 ORDER BY id",
            (agent_id,),
        )
        targets = [
            {
                "id": r["id"],
                "agent_id": r["agent_id"],
                "name": r["name"] or "",
                "target": r["target"],
                "probe_type": r["probe_type"],
                "port": r["port"],
                "timeout": r["timeout"],
                "interval": r["interval"],
                "enabled": bool(r["enabled"]),
            }
            for r in cursor.fetchall()
        ]
        return {"success": True, "data": targets}


# ── CRUD（需要 admin 密码）──────────────────────────────────────────

@router.post("/targets")
async def create_target(payload: TargetCreate):
    """新增监控目标（同时写入 targets 表和 scheduler_jobs 探测任务）"""
    from modules.scheduler import scheduler
    with get_db() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO targets (agent_id, name, target, probe_type, port, timeout, interval, enabled) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    payload.agent_id,
                    payload.name,
                    payload.target,
                    payload.probe_type,
                    payload.port,
                    payload.timeout,
                    payload.interval,
                    1 if payload.enabled else 0,
                ),
            )
            target_id = cursor.lastrowid
            # 同时创建 scheduler_jobs 探测任务
            job_id = f"{payload.agent_id}:{payload.probe_type}:{payload.target}"
            scheduler.add_job(
                job_id=job_id,
                agent_id=payload.agent_id,
                probe_type=payload.probe_type,
                target=payload.target,
                interval_seconds=payload.interval,
                enabled=payload.enabled,
                name=payload.name or payload.target,
            )
            return {"success": True, "id": target_id}
        except Exception as e:
            if "UNIQUE constraint" in str(e):
                raise HTTPException(status_code=409, detail="该目标已存在")
            raise HTTPException(status_code=500, detail=str(e))


@router.get("/targets/{target_id}")
async def get_target(target_id: int):
    """获取单个目标详情"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, agent_id, name, target, probe_type, port, timeout, interval, enabled "
            "FROM targets WHERE id = ?",
            (target_id,),
        )
        r = cursor.fetchone()
        if not r:
            raise HTTPException(status_code=404, detail="目标不存在")
        return {
            "success": True,
            "data": {
                "id": r["id"],
                "agent_id": r["agent_id"],
                "name": r["name"] or "",
                "target": r["target"],
                "probe_type": r["probe_type"],
                "port": r["port"],
                "timeout": r["timeout"],
                "interval": r["interval"],
                "enabled": bool(r["enabled"]),
            },
        }


@router.put("/targets/{target_id}")
async def update_target(target_id: int, payload: TargetUpdate):
    """更新监控目标，同时同步 scheduler_jobs"""
    from modules.scheduler import scheduler
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT agent_id, probe_type, target FROM targets WHERE id = ?", (target_id,))
        old = cursor.fetchone()
        if not old:
            raise HTTPException(status_code=404, detail="目标不存在")

        updates = []
        values = []
        new_agent = old["agent_id"]
        new_probe = old["probe_type"]
        new_target = old["target"]
        if payload.name is not None:
            updates.append("name = ?"); values.append(payload.name)
        if payload.target is not None:
            updates.append("target = ?"); values.append(new_target := payload.target)
        if payload.probe_type is not None:
            updates.append("probe_type = ?"); values.append(new_probe := payload.probe_type)
        if payload.port is not None:
            updates.append("port = ?"); values.append(payload.port)
        if payload.timeout is not None:
            updates.append("timeout = ?"); values.append(payload.timeout)
        if payload.interval is not None:
            updates.append("interval = ?"); values.append(payload.interval)
        if payload.enabled is not None:
            updates.append("enabled = ?"); values.append(1 if payload.enabled else 0)

        if not updates:
            raise HTTPException(status_code=400, detail="没有要更新的字段")

        values.append(target_id)
        cursor.execute(f"UPDATE targets SET {', '.join(updates)} WHERE id = ?", values)

        # 同步更新 scheduler_jobs（用旧 job_id 删，再按新参数建）
        old_job_id = f"{old['agent_id']}:{old['probe_type']}:{old['target']}"
        scheduler.remove_job(old_job_id)
        if payload.enabled is None or payload.enabled:
            new_job_id = f"{new_agent}:{new_probe}:{new_target}"
            scheduler.add_job(new_job_id, new_agent, new_probe, new_target,
                             interval_seconds=payload.interval or 60,
                             enabled=payload.enabled if payload.enabled is not None else True,
                             name=payload.name or new_target)

        return {"success": True}


@router.delete("/targets/{target_id}")
async def delete_target(target_id: int):
    """删除监控目标，同时清理 targets 和 scheduler_jobs"""
    from modules.scheduler import scheduler
    with get_db() as conn:
        cursor = conn.cursor()
        # 先查目标信息，用于删除 scheduler_jobs
        cursor.execute("SELECT agent_id, probe_type, target FROM targets WHERE id = ?", (target_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="目标不存在")
        agent_id, probe_type, target = row["agent_id"], row["probe_type"], row["target"]
        # 删除 targets
        cursor.execute("DELETE FROM targets WHERE id = ?", (target_id,))
        # 删除 scheduler_jobs
        job_id = f"{agent_id}:{probe_type}:{target}"
        scheduler.remove_job(job_id)
        return {"success": True}
