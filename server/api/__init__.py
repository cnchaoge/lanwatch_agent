from fastapi import APIRouter
from . import agents, probe, diag


def register_routers(app):
    app.include_router(agents.router, prefix="/api", tags=["agents"])
    app.include_router(probe.router, prefix="/api", tags=["probe"])
    app.include_router(diag.router, prefix="/api", tags=["diag"])


__all__ = ["register_routers", "agents", "probe", "diag"]
