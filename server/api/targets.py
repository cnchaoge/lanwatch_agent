"""
Targets API - 监控目标管理
GET  /api/targets          - Agent 拉取自己的监控目标
POST /api/targets          - 新增目标
GET  /api/targets/{id}     - 获取单个目标
PUT  /api/targets/{id}     - 更新目标
DELETE /api/targets/{id}   - 删除目标
"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List
from core.database import get_db
from core.auth import verify_admin_password

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


class TargetItem(BaseModel):
    id: int
    agent_id: str
    name: str
    target: str
    probe_type: str
    port: int
    timeout: int
    interval: int
    enabled: bool


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
        # 验证 token
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
async def create_target(payload: TargetCreate, password: str = Query(...)):
    """新增监控目标（需 admin 密码）"""
    verify_admin_password(password)
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
            return {"success": True, "id": target_id}
        except Exception as e:
            if "UNIQUE constraint" in str(e):
                raise HTTPException(status_code=409, detail="该目标已存在")
            raise HTTPException(status_code=500, detail=str(e))


@router.get("/targets/{target_id}")
async def get_target(target_id: int, password: str = Query(...)):
    """获取单个目标详情"""
    verify_admin_password(password)
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
async def update_target(target_id: int, payload: TargetUpdate, password: str = Query(...)):
    """更新监控目标"""
    verify_admin_password(password)
    with get_db() as conn:
        cursor = conn.cursor()
        # 检查是否存在
        cursor.execute("SELECT id FROM targets WHERE id = ?", (target_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="目标不存在")

        # 构建更新语句
        updates = []
        values = []
        if payload.name is not None:
            updates.append("name = ?")
            values.append(payload.name)
        if payload.target is not None:
            updates.append("target = ?")
            values.append(payload.target)
        if payload.probe_type is not None:
            updates.append("probe_type = ?")
            values.append(payload.probe_type)
        if payload.port is not None:
            updates.append("port = ?")
            values.append(payload.port)
        if payload.timeout is not None:
            updates.append("timeout = ?")
            values.append(payload.timeout)
        if payload.interval is not None:
            updates.append("interval = ?")
            values.append(payload.interval)
        if payload.enabled is not None:
            updates.append("enabled = ?")
            values.append(1 if payload.enabled else 0)

        if not updates:
            raise HTTPException(status_code=400, detail="没有要更新的字段")

        values.append(target_id)
        cursor.execute(f"UPDATE targets SET {', '.join(updates)} WHERE id = ?", values)
        return {"success": True}


@router.delete("/targets/{target_id}")
async def delete_target(target_id: int, password: str = Query(...)):
    """删除监控目标"""
    verify_admin_password(password)
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM targets WHERE id = ?", (target_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="目标不存在")
        return {"success": True}