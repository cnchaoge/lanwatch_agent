"""调度器管理 API"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from modules.scheduler import scheduler
from modules.alerter import BUILTIN_RULES

router = APIRouter()


class JobCreate(BaseModel):
    job_id: str
    agent_id: str
    probe_type: str
    target: str
    interval_seconds: int = 300
    enabled: bool = True


@router.post("/scheduler/jobs")
async def add_job(job: JobCreate):
    """创建调度任务"""
    scheduler.add_job(
        job.job_id, job.agent_id, job.probe_type, job.target,
        job.interval_seconds, job.enabled,
    )
    return {"success": True, "job_id": job.job_id}


@router.delete("/scheduler/jobs/{job_id}")
async def delete_job(job_id: str):
    """删除调度任务"""
    scheduler.remove_job(job_id)
    return {"success": True, "job_id": job_id}


@router.get("/scheduler/jobs")
async def list_jobs():
    """列出所有调度任务"""
    return scheduler.get_jobs()


@router.post("/scheduler/jobs/{job_id}/run")
async def run_job(job_id: str):
    """立即执行一次调度任务"""
    ok = scheduler.run_job_now(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"success": True, "job_id": job_id}


@router.get("/scheduler/rules")
async def list_rules():
    """列出内置告警规则"""
    return BUILTIN_RULES


@router.post("/scheduler/reload")
async def reload_jobs():
    """从数据库重新加载所有调度任务"""
    scheduler.reload_jobs_from_db()
    return {"success": True}
