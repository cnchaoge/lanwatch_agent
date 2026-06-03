"""AI 数字分身聊天 API — 基于 OpenAI/MiniMax 的产品知识问答"""
import logging
import os
from fastapi import APIRouter
from pydantic import BaseModel
from typing import List, Optional
import httpx
from core.config import config
from core.database import get_db

logger = logging.getLogger("chat")
router = APIRouter()


# ── 请求/响应模型 ─────────────────────────────────────────────

class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    session_id: str = "anonymous"


class ChatResponse(BaseModel):
    success: bool
    message: Optional[dict] = None
    error: Optional[str] = None


# ── 系统提示词（产品知识库） ──────────────────────────────────

SYSTEM_PROMPT = """你是 LANWatch AI 助理，一个企业网络监控平台的产品专家。你热情、专业、简洁，用中文回答所有问题。

## 产品简介

LANWatch（全称 Lanwatch）是一款面向中小企业的轻量级网络监控平台。由作者 @cnchaoge 开发，MIT 开源协议。
官网：http://lanwatch.net
联系电话/微信：185-3172-9777
当前版本：v1.3.0（2026-05-04 发布）

## 核心能力

1. 多协议探测：ICMP Ping / Traceroute / TCP 端口扫描 / DNS 解析 / HTTP 健康检查 / SNMP 采集
2. 定时调度：基于 APScheduler 的灵活定时探测，每 60 秒上报
3. 拓扑发现：通过 ARP/LLDP/CDP 自动发现网络拓扑，零噪音不发包
4. 告警推送：8 条内置规则，支持 Server酱(微信)、钉钉机器人、飞书机器人
5. 智能诊断引擎：12 条诊断规则
6. 故障传播链：BFS 拓扑传播分析，自动识别根因
7. 引导式排查向导：5 种故障场景

## 技术架构

- 后端：FastAPI + APScheduler + SQLite
- 前端：原生 HTML/CSS/JS + Chart.js
- 部署：Docker / docker-compose 或 Python 直接运行
- 客户端：Windows (PyInstaller)、Linux、macOS、OpenWrt 路由器

## 部署方式

```bash
cd server && pip install -r requirements.txt && python main.py
# 访问 http://localhost:8000
```

Docker: docker-compose up -d

Windows 客户端：下载 exe，双击运行，输入企业名称注册，完成。

## FAQ

- 需要专业网管吗？不需要。下载运行，5 分钟完成部署。
- 断网怎么通知？微信 Server酱 推送，3 分钟自动告警。
- 收费吗？现阶段 MVP 免费试用。
- 支持 Mac 吗？Mac 客户端正在开发。

## 对话风格

你的回答必须遵守以下规则，这是最重要的要求：

1. 说人话：像朋友聊天一样自然，不要用"首先/其次/此外"这类结构词，不要列点
2. 简短：能一句话说清绝不说两句。复杂问题最多3句。
3. 直接回答：不要铺垫，不要总结，不要"总的来说"
4. 少用 emoji：每句话最多用一个，不是每句都要加
5. 不确定就说不知道：不要编造，不要猜测
6. 不要反问用户：除非用户主动问你意见"""


# ── 聊天端点 ──────────────────────────────────────────────────

@router.post("/chat")
async def chat(req: ChatRequest):
    """与 LANWatch AI 助理对话"""
    api_key = (config.LLM_API_KEY or os.environ.get("LLM_API_KEY", "") or os.environ.get("OPENAI_API_KEY", ""))
    if not api_key:
        logger.warning("LLM_API_KEY 未配置")
        return ChatResponse(success=False, error="AI 助理暂未配置 API Key，请联系管理员设置")

    api_base = (config.LLM_API_BASE or os.environ.get("LLM_API_BASE", "") or "https://api.openai.com/v1")
    model = (config.LLM_MODEL or os.environ.get("LLM_MODEL", "") or "gpt-4o-mini")
    url = api_base.rstrip("/") + "/chat/completions"

    # 记录用户消息
    try:
        with get_db() as conn:
            for m in req.messages:
                conn.execute(
                    "INSERT INTO chat_logs (session_id, role, content) VALUES (?, ?, ?)",
                    (req.session_id, m.role, m.content),
                )
    except Exception as e:
        logger.warning("记录聊天消息失败: %s", e)

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        *[m.dict() for m in req.messages],
                    ],
                    "temperature": 0.7,
                    "max_tokens": 1024,
                },
            )
            data = resp.json()

        if "error" in data:
            logger.error("LLM API 错误: %s", data["error"])
            return ChatResponse(success=False, error=f"AI 响应错误: {data['error'].get('message', '未知错误')}")

        reply = data["choices"][0]["message"]["content"]

        # 记录 AI 回复
        try:
            with get_db() as conn:
                conn.execute(
                    "INSERT INTO chat_logs (session_id, role, content) VALUES (?, ?, ?)",
                    (req.session_id, "assistant", reply),
                )
        except Exception as e:
            logger.warning("记录 AI 回复失败: %s", e)

        return ChatResponse(success=True, message={"role": "assistant", "content": reply})

    except httpx.TimeoutException:
        logger.error("LLM API 超时")
        return ChatResponse(success=False, error="AI 响应超时，请稍后重试")
    except Exception as e:
        logger.exception("Chat API 异常")
        return ChatResponse(success=False, error=f"服务器错误: {str(e)}")


# ── 聊天记录管理 ──────────────────────────────────────────────

@router.get("/chat/logs")
async def get_chat_logs(limit: int = 50):
    """获取最近的聊天记录（按会话分组）"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, session_id, role, content, created_at FROM chat_logs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    sessions = {}
    for r in rows:
        sid = r["session_id"]
        if sid not in sessions:
            sessions[sid] = {"session_id": sid, "first_msg": r["created_at"], "messages": []}
        sessions[sid]["messages"].append({
            "id": r["id"], "role": r["role"],
            "content": r["content"], "created_at": r["created_at"],
        })
    result = sorted(sessions.values(), key=lambda s: s["first_msg"], reverse=True)
    for s in result:
        s["messages"].reverse()
    return {"success": True, "sessions": result, "total": len(rows)}


@router.delete("/chat/logs/{session_id}")
async def delete_chat_logs(session_id: str):
    """删除某个会话的聊天记录"""
    with get_db() as conn:
        conn.execute("DELETE FROM chat_logs WHERE session_id = ?", (session_id,))
    return {"success": True}
