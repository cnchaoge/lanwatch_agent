import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from core.config import config
from core.database import init_db
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
from web import register_web
from modules.scheduler import scheduler
from modules.snmp_manager import snmp_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    print(f"[lanwatch_agent] 数据库初始化完成: {config.DB_PATH}")
    scheduler.reload_jobs_from_db()
    snmp_manager.ensure_snmp_jobs()
    scheduler.start()
    print(f"[lanwatch_agent] 探测调度器已启动")
    yield
    scheduler.shutdown()
    print(f"[lanwatch_agent] 探测调度器已停止")


app = FastAPI(title="Lanwatch", version="1.0.0", description="企业网络监控平台 - 服务端 API", lifespan=lifespan)

if config.CORS_ORIGINS:
    app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

app.include_router(agents_router)
app.include_router(probe_router)
app.include_router(diag_router)
app.include_router(probes_router, prefix="/api")
app.include_router(scheduler_router, prefix="/api")
app.include_router(snmp_router, prefix="/api")
app.include_router(alert_router, prefix="/api")
app.include_router(history_router, prefix="/api")
app.include_router(topology_router, prefix="/api")
app.include_router(diagnosis_router, prefix="/api")
app.include_router(wizard_router, prefix="/api")
app.include_router(propagation_router, prefix="/api")

register_web(app)

@app.get("/api/version")
async def api_version():
    from version import get_version_info
    return get_version_info()

@app.get("/health")
async def health_check():
    return {"status": "ok", "db": config.DB_PATH}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
