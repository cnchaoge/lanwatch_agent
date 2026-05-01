import logging
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from core.config import config
from core.database import init_db
from core.logging import setup_logging
from api.agents import router as agents_router
from api.probe import router as probe_router
from api.diag import router as diag_router
from api.probes import router as probes_router
from api.scheduler_api import router as scheduler_router
from api.snmp_api import router as snmp_router
from api.alert_api import router as alert_router
from api.history_api import router as history_router
from api.diagnosis_api import router as diagnosis_router
from api.topology_api import router as topology_router
from api.wizard_api import router as wizard_router
from api.propagation_api import router as propagation_router
from api.admin_api import router as admin_router
from web import register_web
from modules.scheduler import scheduler
from modules.snmp_manager import snmp_manager
from modules.dataretention import run_cleanup, get_retention_info, start_cleanup_scheduler, stop_cleanup_scheduler

logger = logging.getLogger("lanwatch")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(log_level=config.LOG_LEVEL)
    init_db()
    logger.info("数据库初始化完成: %s", config.DB_PATH)
    scheduler.reload_jobs_from_db()
    snmp_manager.ensure_snmp_jobs()
    scheduler.start()
    logger.info("探测调度器已启动")
    start_cleanup_scheduler()
    yield
    stop_cleanup_scheduler()
    scheduler.shutdown()
    logger.info("探测调度器已停止")


app = FastAPI(title="Lanwatch", version="1.0.0", description="企业网络监控平台 - 服务端 API", lifespan=lifespan)

import time

if config.CORS_ORIGINS:
    app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def request_logging(request: Request, call_next):
    start = time.monotonic()
    response = await call_next(request)
    cost = (time.monotonic() - start) * 1000
    logger.info("%s %s -> %d (%.0fms)", request.method, request.url.path, response.status_code, cost)
    return response


# ── 全局异常处理 ────────────────────────────────────────────────────

from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"success": False, "error": "请求参数错误", "detail": exc.errors()},
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "error": exc.detail},
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"success": False, "error": "服务器内部错误"},
    )


# ── 路由注册 ────────────────────────────────────────────────────────

app.include_router(agents_router, prefix="/api")   # 静态 /agents 必须在 /{agent_id} 之前
app.include_router(probe_router, prefix="/api")
app.include_router(diag_router, prefix="/api")
app.include_router(probes_router, prefix="/api")
app.include_router(scheduler_router, prefix="/api")
app.include_router(snmp_router, prefix="/api")
app.include_router(alert_router, prefix="/api")
app.include_router(history_router, prefix="/api")
app.include_router(topology_router, prefix="/api")
app.include_router(diagnosis_router, prefix="/api")
app.include_router(wizard_router, prefix="/api")
app.include_router(propagation_router, prefix="/api")
app.include_router(admin_router, prefix="/api")

register_web(app)

@app.get("/api/version")
async def api_version():
    from version import get_version_info
    return get_version_info()

@app.get("/health")
async def health_check():
    return {"status": "ok", "db": config.DB_PATH}


@app.post("/api/cleanup")
async def manual_cleanup():
    """手动触发数据清理"""
    result = run_cleanup()
    return {"success": True, "data": result}


@app.get("/api/cleanup/info")
async def cleanup_info():
    """查看保留天数配置和各表数据量"""
    return {"success": True, "data": get_retention_info()}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
