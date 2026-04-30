"""数据自动清理：按保留天数删除过期数据，回收 SQLite 磁盘空间"""
import logging
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from core.database import get_db
from core.config import config

logger = logging.getLogger("dataretention")

RETENTION_RULES = {
    "probe_results": {
        "column": "created_at",
        "days": config.RETENTION_PROBE_DAYS,
        "label": "探测结果",
    },
    "snmp_metrics": {
        "column": "timestamp",
        "days": config.RETENTION_SNMP_DAYS,
        "label": "SNMP 指标",
    },
    "alert_log": {
        "column": "created_at",
        "days": config.RETENTION_ALERT_DAYS,
        "label": "告警日志",
    },
    "diag_reports": {
        "column": "created_at",
        "days": config.RETENTION_DIAG_DAYS,
        "label": "诊断报告",
    },
}


def _delete_old(table: str, column: str, days: int) -> int:
    """删除指定表中超过 days 天的数据，返回删除行数"""
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    with get_db() as conn:
        cur = conn.execute(
            f"DELETE FROM {table} WHERE {column} < ?", (cutoff,)
        )
        deleted = cur.rowcount
        logger.info("[清理] %s 已删除 %d 行 (保留 %d 天)", table, deleted, days)
        return deleted


def _vacuum() -> bool:
    """回收 SQLite 磁盘空间"""
    try:
        with get_db() as conn:
            conn.execute("VACUUM")
        logger.info("[清理] VACUUM 完成，磁盘空间已回收")
        return True
    except Exception as e:
        logger.warning("[清理] VACUUM 失败: %s", e)
        return False


def run_cleanup() -> dict:
    """执行一轮完整清理，返回各表删除行数"""
    logger.info("[清理] ===== 开始数据清理 =====")
    totals = {"tables": {}, "vacuum": False}
    total_deleted = 0
    for table, rule in RETENTION_RULES.items():
        try:
            n = _delete_old(table, rule["column"], rule["days"])
            totals["tables"][table] = {"label": rule["label"], "deleted": n}
            total_deleted += n
        except Exception as e:
            logger.error("[清理] %s 清理失败: %s", table, e)
            totals["tables"][table] = {"label": rule["label"], "error": str(e)}

    if total_deleted > 0:
        totals["vacuum"] = _vacuum()

    totals["total_deleted"] = total_deleted
    logger.info("[清理] ===== 清理完成，共删除 %d 行 =====", total_deleted)
    return totals


def get_retention_info() -> dict:
    """返回当前保留天数配置和各表数据量"""
    info = {"retention_days": {}, "row_counts": {}}
    for table, rule in RETENTION_RULES.items():
        info["retention_days"][table] = {
            "days": rule["days"],
            "label": rule["label"],
        }
        try:
            with get_db() as conn:
                cur = conn.execute(f"SELECT COUNT(*) AS cnt FROM {table}")
                info["row_counts"][table] = cur.fetchone()["cnt"]
        except Exception:
            info["row_counts"][table] = -1
    return info


# ── 调度器单例 ──────────────────────────────────────────────────────

_cleanup_scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
_CLEANUP_JOB_ID = "data_retention_cleanup"


def start_cleanup_scheduler():
    """启动定时清理任务（默认每 6 小时执行一次）"""
    if _cleanup_scheduler.running:
        return
    _cleanup_scheduler.add_job(
        run_cleanup,
        trigger=IntervalTrigger(hours=6),
        id=_CLEANUP_JOB_ID,
        replace_existing=True,
    )
    _cleanup_scheduler.start()
    logger.info("[清理] 定时任务已启动，每 6 小时执行一次")


def stop_cleanup_scheduler():
    if _cleanup_scheduler.running:
        _cleanup_scheduler.shutdown(wait=False)
        logger.info("[清理] 定时任务已停止")
