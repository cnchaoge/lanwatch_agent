"""探测历史 API：查询结果历史、趋势数据、设备状态汇总"""
import logging
from fastapi import APIRouter, Query
from typing import Optional

logger = logging.getLogger("history_api")
from datetime import datetime, timedelta
from core.database import get_db

router = APIRouter()


@router.get("/history/probe_results")
async def get_probe_history(
    agent_id: Optional[str] = None,
    probe_type: Optional[str] = None,
    target: Optional[str] = None,
    hours: int = Query(default=24, ge=1, le=720),
    limit: int = Query(default=200, ge=1, le=1000),
):
    """查询探测结果历史"""
    cutoff = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")

    with get_db() as conn:
        cursor = conn.cursor()
        sql = "SELECT * FROM probe_results WHERE created_at >= ?"
        params: list = [cutoff]

        if agent_id:
            sql += " AND agent_id = ?"
            params.append(agent_id)
        if probe_type:
            sql += " AND probe_type = ?"
            params.append(probe_type)
        if target:
            sql += " AND target = ?"
            params.append(target)

        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        cursor.execute(sql, params)
        rows = cursor.fetchall()

        return {
            "count": len(rows),
            "hours": hours,
            "results": [dict(row) for row in rows],
        }


@router.get("/history/trends/ping")
async def get_ping_trends(
    target: str = Query(...),
    agent_id: Optional[str] = None,
    hours: int = Query(default=24, ge=1, le=168),
):
    """获取 ping 延迟趋势数据（用于绘图）"""
    cutoff = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")

    with get_db() as conn:
        cursor = conn.cursor()
        sql = """SELECT created_at, rtt_ms, status
                 FROM probe_results
                 WHERE probe_type='ping'
                   AND target=?
                   AND created_at >= ?"""
        params: list = [target, cutoff]

        if agent_id:
            sql += " AND agent_id = ?"
            params.append(agent_id)

        sql += " ORDER BY created_at ASC LIMIT 500"
        cursor.execute(sql, params)

        return {
            "target": target,
            "agent_id": agent_id,
            "hours": hours,
            "data": [
                {
                    "timestamp": row["created_at"],
                    "rtt_ms": row["rtt_ms"],
                    "loss": 1.0 if row["status"] == "unreachable" else 0.0,
                }
                for row in cursor.fetchall()
            ],
        }


@router.get("/history/device_status")
async def get_device_status_summary():
    """获取所有设备的最新状态汇总"""
    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute(
            """SELECT pr.* FROM probe_results pr
               INNER JOIN (
                   SELECT agent_id, MAX(created_at) as max_time
                   FROM probe_results
                   GROUP BY agent_id
               ) latest
               ON pr.agent_id = latest.agent_id
                AND pr.created_at = latest.max_time
               ORDER BY pr.created_at DESC
               LIMIT 200"""
        )
        rows = cursor.fetchall()

        device_status = {}
        for row in rows:
            aid = row["agent_id"]
            if aid not in device_status:
                device_status[aid] = {"agent_id": aid, "last_seen": None, "probes": {}}
            device_status[aid]["probes"][f"{row['probe_type']}:{row['target']}"] = {
                "status": row["status"],
                "rtt_ms": row["rtt_ms"],
                "last_check": row["created_at"],
            }
            if (
                not device_status[aid]["last_seen"]
                or row["created_at"] > device_status[aid]["last_seen"]
            ):
                device_status[aid]["last_seen"] = row["created_at"]

        # last_seen 是 SQLite UTC 字符串，转 epoch 秒供前端比较
        for dev in device_status.values():
            if dev["last_seen"]:
                try:
                    dt = datetime.fromisoformat(dev["last_seen"] + "+00:00")
                    dev["last_seen_ts"] = dt.timestamp()
                except Exception as e:
                    logger.warning("解析设备上线时间戳失败 [%s]: %s", dev.get("device_ip", "?"), e)

        return {
            "count": len(device_status),
            "devices": list(device_status.values()),
        }


@router.get("/history/snmp_metrics")
async def get_snmp_metrics_history(
    device_ip: str = Query(...),
    oid: Optional[str] = None,
    hours: int = Query(default=24, ge=1, le=720),
    limit: int = Query(default=500, ge=1, le=2000),
):
    """查询 SNMP 指标历史"""
    cutoff = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")

    with get_db() as conn:
        cursor = conn.cursor()
        sql = "SELECT * FROM snmp_metrics WHERE device_ip = ? AND timestamp >= ?"
        params: list = [device_ip, cutoff]

        if oid:
            sql += " AND oid = ?"
            params.append(oid)

        sql += " ORDER BY timestamp ASC LIMIT ?"
        params.append(limit)

        cursor.execute(sql, params)
        rows = cursor.fetchall()

        return {
            "device_ip": device_ip,
            "oid": oid,
            "hours": hours,
            "count": len(rows),
            "metrics": [dict(row) for row in rows],
        }
