"""AI 数字分身聊天 API — 基于 OpenAI 的产品知识问答"""
import logging
from fastapi import APIRouter
from pydantic import BaseModel
from typing import List, Optional
import os
import httpx
from core.config import config

logger = logging.getLogger("chat")
router = APIRouter()


# ── 请求/响应模型 ─────────────────────────────────────────────

class ChatMessage(BaseModel):
    role: str  # "user" | "assistant" | "system"
    content: str


class ChatRequest(BaseModel):
    messages: List[ChatMessage]


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
5. 智能诊断引擎：12 条诊断规则，覆盖 Ping/HTTP/DNS/端口异常
6. 故障传播链：BFS 拓扑传播分析，自动识别根因和影响范围
7. 引导式排查向导：5 种故障场景，逐步引导排查

## 技术架构

- 后端：FastAPI + APScheduler + SQLite
- 前端：原生 HTML/CSS/JS + Chart.js
- 部署：Docker / docker-compose 或 Python 直接运行
- 客户端：Windows (PyInstaller)、Linux、macOS、OpenWrt 路由器

## 部署方式

### 服务端部署
```bash
cd server
pip install -r requirements.txt
python main.py
# 访问 http://localhost:8000
```

### Docker 部署
```bash
docker-compose up -d
```

### Windows 客户端
下载 exe，双击运行，输入企业名称注册，完成。运行后隐藏到系统托盘，开机自启。

## 常见问题

- Q: 需要专业网管吗？ A: 不需要。下载运行，5 分钟完成部署。
- Q: 数据存在哪？ A: 云端服务器，企业间数据完全隔离。
- Q: 断网怎么通知？ A: 微信 Server酱 推送，3 分钟无人值守自动告警。
- Q: 收费吗？ A: 现阶段 MVP 免费试用。
- Q: 支持 Mac 吗？ A: Mac 客户端正在开发。
- Q: 支持哪些设备？ A: 不限数量，每个企业独立数据库。

## API 概览

主要端点（完整参考见文档）：
- POST /api/register - 设备注册
- GET /api/agents - 企业列表
- GET /api/probe/ping - Ping 探测
- GET /api/probe/traceroute - 路由追踪
- GET /api/topology - 拓扑查询
- GET /api/alerts - 告警列表
- POST /api/diagnosis/diagnose - 诊断

## 项目历史

项目从 2026 年 4 月开始开发，经历了从 Windows 客户端到全平台支持的演进。
v1.0.0 正式版于 2026-04-29 发布，增加了诊断引擎、排查向导、故障传播链等核心功能。
v1.3.0 新增 targets 监控目标表和 enterprise 企业端聚合页面。

## 对话风格

- 用中文回答，热情友好
- 回答简洁有重点，必要时分点说明
- 遇到不确定的问题坦诚说不知道，不编造
- 可以询问客户的使用场景，给出针对性建议
- 适当使用 emoji 让对话更轻松"""


# ── 聊天端点 ──────────────────────────────────────────────────

@router.post("/chat")
async def chat(req: ChatRequest):
    """与 LANWatch AI 助理对话"""
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        logger.warning("OPENAI_API_KEY 未配置")
        return ChatResponse(success=False, error="AI 助理暂未配置 API Key，请联系管理员设置")

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "gpt-4o-mini",
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
            logger.error("OpenAI API 错误: %s", data["error"])
            return ChatResponse(success=False, error=f"AI 响应错误: {data['error'].get('message', '未知错误')}")

        reply = data["choices"][0]["message"]["content"]
        return ChatResponse(success=True, message={"role": "assistant", "content": reply})

    except httpx.TimeoutException:
        logger.error("OpenAI API 超时")
        return ChatResponse(success=False, error="AI 响应超时，请稍后重试")
    except Exception as e:
        logger.exception("Chat API 异常")
        return ChatResponse(success=False, error=f"服务器错误: {str(e)}")

