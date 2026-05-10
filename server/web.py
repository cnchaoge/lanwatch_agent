"""Web 前端服务 — Jinja2 模板渲染 + 静态文件"""
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse


def register_web(app: FastAPI):
    base = Path(__file__).parent
    templates_dir = base / "templates"
    static_dir = base / "static"
    client_dir = base / "client"

    templates_dir.mkdir(exist_ok=True)
    static_dir.mkdir(exist_ok=True)
    client_dir.mkdir(exist_ok=True)

    templates = Jinja2Templates(directory=str(templates_dir))

    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # 客户端下载
    client_exe = client_dir / "LanwatchAgent.exe"
    if client_exe.exists():
        @app.get("/client.exe")
        async def download_client():
            return FileResponse(str(client_exe), media_type="application/octet-stream",
                                filename="LanwatchAgent.exe")

    @app.get("/", response_class=HTMLResponse)
    async def serve_index(request: Request):
        return templates.TemplateResponse(request, "index.html")

    named_pages = ["admin", "agents", "ping_overview", "download", "monitor", "setup", "mobile"]
    for name in named_pages:
        def _add_redirect(page=name):
            @app.get(f"/{page}", response_class=RedirectResponse)
            async def redirect_to_html():
                return RedirectResponse(url=f"/{page}.html")
        _add_redirect()

    @app.get("/api/{path:path}")
    async def api_404(path: str):
        return {"success": False, "error": "API 路由不存在"}, 404

    @app.get("/{page_name}.html", response_class=HTMLResponse)
    async def serve_page(page_name: str, request: Request):
        tmpl = f"{page_name}.html"
        if (templates_dir / tmpl).is_file():
            return templates.TemplateResponse(request, tmpl)
        static_file = static_dir / tmpl
        if static_file.is_file():
            return FileResponse(str(static_file), media_type="text/html")
        return {"success": False, "error": f"页面 {tmpl} 不存在"}, 404

    @app.get("/agent/{agent_id}", response_class=HTMLResponse)
    async def agent_detail(request: Request, agent_id: str):
        return templates.TemplateResponse(request, "agent_detail.html")

    @app.get("/enterprise/{agent_id}", response_class=HTMLResponse)
    async def enterprise_dashboard(request: Request, agent_id: str):
        return templates.TemplateResponse(request, "enterprise.html")

    @app.get("/ping_detail/{monitor_id}", response_class=HTMLResponse)
    async def ping_detail(request: Request, monitor_id: str):
        return templates.TemplateResponse(request, "ping_detail.html")

    @app.get("/snmp_detail/{device_id}", response_class=HTMLResponse)
    async def snmp_detail(request: Request, device_id: str):
        return templates.TemplateResponse(request, "snmp_detail.html")