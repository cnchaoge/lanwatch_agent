"""Web 前端服务 — 根路径返回 index.html"""
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse


def register_web(app: FastAPI):
    base = Path(__file__).parent
    templates_dir = base / "templates"
    static_dir = base / "static"

    templates_dir.mkdir(exist_ok=True)
    static_dir.mkdir(exist_ok=True)

    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/")
    async def serve_index():
        index_file = templates_dir / "index.html"
        if index_file.exists():
            return FileResponse(str(index_file), media_type="text/html")
        return {"error": "index.html not found", "hint": "place index.html in templates/"}

