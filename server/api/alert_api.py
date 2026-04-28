"""告警管理 API：查询/确认/统计/渠道配置/规则列表"""
from fastapi import APIRouter, Query, HTTPException
from typing import Optional
from datetime import datetime, timedelta
from pydantic import BaseModel
from core.database import get_db
from core.config import config
from core.auth import verify_admin_password
from modules.alerter import alerter, BUILTIN_RULES

router = APIRouter()


class AlertChannelConfig(BaseModel):
    sckey: Optional[str] = None
    dingtalk_webhook: Optional[str] = None
    feishu_webhook: Optional[str] = None


@router.get("/alerts")
async def get_alerts(
    agent_id: Optional[str] = None,
    level: Optional[str] = None,
    hours: int = Query(default=24, ge=1, le=720),
    limit: int = Query(default=100, ge=1, le=500),
):
    """查询告警历史"""
    cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()

    with get_db() as conn:
        cursor = conn.cursor()
        sql = "SELECT * FROM alert_log WHERE created_at >= ?"
        params: list = [cutoff]

        if agent_id:
            sql += " AND agent_id = ?"
            params.append(agent_id)
        if level:
            sql += " AND level = ?"
            params.append(level)

        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        cursor.execute(sql, params)
        rows = cursor.fetchall()

        return {
            "count": len(rows),
            "hours": hours,
            "alerts": [dict(row) for row in rows],
        }


@router.get("/alerts/stats")
async def get_alert_stats(hours: int = Query(default=24, ge=1, le=720)):
    """告警统计：按级别、设备、类型分布 + 环比"""
    cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
    cutoff_prev = (datetime.now() - timedelta(hours=hours * 2)).isoformat()

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute(
            """SELECT level, COUNT(*) as cnt
               FROM alert_log WHERE created_at >= ?
               GROUP BY level""",
            (cutoff,),
        )
        by_level = {row["level"]: row["cnt"] for row in cursor.fetchall()}
        current_total = sum(by_level.values())

        cursor.execute(
            """SELECT COUNT(*) as cnt FROM alert_log
               WHERE created_at >= ? AND created_at < ?""",
            (cutoff_prev, cutoff),
        )
        prev_total = cursor.fetchone()["cnt"]

        cursor.execute(
            """SELECT agent_id, COUNT(*) as cnt
               FROM alert_log WHERE created_at >= ?
               GROUP BY agent_id ORDER BY cnt DESC LIMIT 10""",
            (cutoff,),
        )
        by_agent = [
            {"agent_id": r["agent_id"], "count": r["cnt"]}
            for r in cursor.fetchall()
        ]

        cursor.execute(
            """SELECT alert_type, COUNT(*) as cnt
               FROM alert_log WHERE created_at >= ?
               GROUP BY alert_type ORDER BY cnt DESC LIMIT 10""",
            (cutoff,),
        )
        by_type = [
            {"type": r["alert_type"], "count": r["cnt"]}
            for r in cursor.fetchall()
        ]

        change_pct = None
        if prev_total > 0:
            change_pct = round(
                (current_total - prev_total) / prev_total * 100, 1
            )

        return {
            "period_hours": hours,
            "current_period": {
                "total": current_total,
                "by_level": by_level,
                "change_vs_prev_pct": change_pct,
                "prev_period_total": prev_total,
            },
            "by_agent_top10": by_agent,
            "by_type_top10": by_type,
        }


@router.post("/alerts/{alert_id}/ack")
async def acknowledge_alert(alert_id: int):
    """确认告警"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE alert_log SET message = message || ' [已确认]' WHERE id = ?",
            (alert_id,),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="告警不存在")
        return {"success": True, "alert_id": alert_id, "message": "告警已确认"}


@router.delete("/alerts/clear")
async def clear_alerts(
    agent_id: Optional[str] = None,
    before_hours: int = Query(default=168, ge=1),
    password: Optional[str] = Query(None),
):
    """清理历史告警（管理员操作）"""
    if config.ADMIN_PASSWORD and config.ADMIN_PASSWORD != "admin":
        verify_admin_password(password)

    cutoff = (datetime.now() - timedelta(hours=before_hours)).isoformat()

    with get_db() as conn:
        cursor = conn.cursor()
        if agent_id:
            cursor.execute(
                "DELETE FROM alert_log WHERE created_at < ? AND agent_id = ?",
                (cutoff, agent_id),
            )
        else:
            cursor.execute(
                "DELETE FROM alert_log WHERE created_at < ?", (cutoff,)
            )
        deleted = cursor.rowcount
        return {
            "success": True,
            "deleted": deleted,
            "before_hours": before_hours,
        }


@router.get("/alerts/channels")
async def get_alert_channels():
    """查询告警渠道配置状态（不返回具体 URL）"""
    return {
        "serverchan": {
            "enabled": bool(config.SCKEY),
            "configured": bool(config.SCKEY),
        },
        "dingtalk": {
            "enabled": bool(config.DINGTALK_WEBHOOK),
            "configured": bool(config.DINGTALK_WEBHOOK),
        },
        "feishu": {
            "enabled": bool(config.FEISHU_WEBHOOK),
            "configured": bool(config.FEISHU_WEBHOOK),
        },
    }


@router.post("/alerts/channels")
async def update_alert_channels(
    payload: AlertChannelConfig,
    password: Optional[str] = Query(None),
):
    """更新告警渠道配置（管理员操作，运行时生效，重启恢复）"""
    if config.ADMIN_PASSWORD and config.ADMIN_PASSWORD != "admin":
        verify_admin_password(password)

    if payload.sckey is not None:
        config.SCKEY = payload.sckey
    if payload.dingtalk_webhook is not None:
        config.DINGTALK_WEBHOOK = payload.dingtalk_webhook
    if payload.feishu_webhook is not None:
        config.FEISHU_WEBHOOK = payload.feishu_webhook

    return {
        "success": True,
        "message": "配置已更新（重启后需重新设置，建议使用环境变量）",
        "channels": {
            "serverchan": bool(config.SCKEY),
            "dingtalk": bool(config.DINGTALK_WEBHOOK),
            "feishu": bool(config.FEISHU_WEBHOOK),
        },
    }


@router.get("/alerts/rules")
async def get_alert_rules():
    """获取所有内置告警规则"""
    return {
        "count": len(BUILTIN_RULES),
        "rules": [
            {
                "type": r["type"],
                "name": r["name"],
                "level": r["level"],
                "description": r["description"],
                "threshold": r.get("threshold"),
            }
            for r in BUILTIN_RULES
        ],
    }


@router.post("/alerts/test")
async def test_alert(
    channel: str = Query(...),  # serverchan | dingtalk | feishu
    password: Optional[str] = Query(None),
):
    """发送测试告警（验证渠道配置是否正确）"""
    if config.ADMIN_PASSWORD and config.ADMIN_PASSWORD != "admin":
        verify_admin_password(password)

    title = "[Lanwatch] 测试告警"
    message = "这是一条测试告警，如果收到说明告警渠道配置正确"

    if channel == "serverchan":
        alerter._dispatch_serverchan(title, message)
    elif channel == "dingtalk":
        alerter._dispatch_dingtalk(f"{title}\n{message}")
    elif channel == "feishu":
        alerter._dispatch_feishu(f"{title}\n{message}")
    else:
        raise HTTPException(
            status_code=400,
            detail="未知渠道，可用: serverchan | dingtalk | feishu",
        )

    return {
        "success": True,
        "channel": channel,
        "message": "测试告警已发送，请检查是否收到",
    }
