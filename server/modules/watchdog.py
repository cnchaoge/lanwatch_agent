"""网络告警看门狗

定时扫描两类信号，把「客户端上报」翻译成「人该知道的告警」：

1. Agent 失联（agent_silent）
   客户端每 60 秒上报一次。超过 AGENT_SILENCE_SECONDS 没有更新 last_seen，
   说明客户端进程挂了 / 机器断电了 / 网络断了且没能自报。
   这是客户端上报链路本身失灵时的唯一兜底。

2. 断线事件（network_offline / network_recovered）
   network_events 表里 end_time 为空 = 还在断；刚填上 end_time = 刚恢复。
   告警文案带断点跳数、已持续时长、根因提示。

去重策略：
- 断线/恢复按 event 的 local_id 各自成键，同一次事件只推一次
- 持续断线每 OFFLINE_REMIND_SECONDS 追一条提醒
- Agent 失联按 AGENT_SILENCE_SECONDS 的节奏复查，用 alert_log 判断最近是否已推
"""
import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from core.database import get_db
from core.config import config
from modules.alerter import alerter

logger = logging.getLogger("watchdog")

_WATCHDOG_JOB_ID = "watchdog"


def _parse_ts(raw) -> datetime:
    """兼容两种时间格式：
    服务端写的 isoformat  2026-10-22T10:00:00.123456
    客户端写的 strftime   2026-10-22 10:00:00
    """
    if not raw:
        return None
    s = str(raw).strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _agent_label(agent_id: str) -> str:
    """取企业名，没有就退回 agent_id"""
    try:
        with get_db() as conn:
            row = conn.execute(
                "SELECT name FROM agents WHERE agent_id = ?", (agent_id,)
            ).fetchone()
        if row and row["name"]:
            return row["name"]
    except Exception:
        pass
    return agent_id


def _recently_alerted(agent_id: str, alert_type: str, within_seconds: int) -> bool:
    """alert_log 里最近是否已经推过同类告警

    注意：alert_log.created_at 是 SQLite CURRENT_TIMESTAMP，格式为
    'YYYY-MM-DD HH:MM:SS'（空格分隔、无微秒）。必须用同一格式做字符串比较，
    否则 isoformat() 的 'T' 分隔会让比较结果恒为「不是最近」。
    """
    cutoff = (datetime.now() - timedelta(seconds=within_seconds)).strftime(
        "%Y-%m-%d %H:%M:%S")
    try:
        with get_db() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM alert_log "
                "WHERE agent_id = ? AND alert_type = ? AND created_at >= ?",
                (agent_id, alert_type, cutoff),
            ).fetchone()
        return bool(row and row["c"])
    except Exception:
        return False


# ── 1. Agent 失联 ──────────────────────────────────────────────

def check_agent_silence():
    cutoff = datetime.now() - timedelta(seconds=config.AGENT_SILENCE_SECONDS)
    with get_db() as conn:
        # 已软删除（客户端主动卸载）的设备不再参与失联告警，
        # 否则每卸载一台，服务端就会永远把它当成掉线设备反复报警
        rows = conn.execute(
            "SELECT agent_id, name, last_seen FROM agents WHERE deleted_at IS NULL"
        ).fetchall()

    fired = 0
    for r in rows:
        r = dict(r)
        last = _parse_ts(r["last_seen"])
        if last is None:
            continue
        if last >= cutoff:
            continue

        silent_for = int((datetime.now() - last).total_seconds())
        if _recently_alerted(r["agent_id"], "agent_silent", config.AGENT_SILENCE_SECONDS):
            continue

        mins = silent_for // 60
        label = r["name"] or r["agent_id"]
        alerter.dispatch(
            "agent_silent", r["agent_id"],
            f"【{label}】客户端已 {mins} 分钟没有任何上报\n"
            f"最后上报：{r['last_seen']}\n"
            f"可能是：客户端进程退出 / 机器断电 / 网络中断且无法自报。"
            f"请检查该机器，或登录后台确认现场状态。",
            "error",
        )
        fired += 1

    if fired:
        logger.warning("[看门狗] Agent 失联告警 %d 条", fired)


# ── 2. 断线事件 ────────────────────────────────────────────────

_HOP_TEXT = {
    0: "本机网卡不可达",
    1: "网关不可达（局域网内部断）",
    2: "外网不可达（DNS / 公网不通）",
}


def _event_message(ev, duration: int) -> str:
    label = _agent_label(ev["agent_id"])
    hop = ev["hop_count"]
    hop_text = _HOP_TEXT.get(hop, f"断在第 {hop} 跳")
    lines = [
        f"【{label}】检测到网络中断",
        f"开始时间：{ev['start_time']}",
        f"持续：{duration // 60} 分 {duration % 60} 秒",
        f"位置：{hop_text}",
    ]
    if ev.get("error_message"):
        lines.append(f"现象：{ev['error_message']}")
    if ev.get("diag_conclusion"):
        lines.append(f"诊断：{ev['diag_conclusion']}")
    if ev.get("root_cause_hint"):
        lines.append(f"根因：{ev['root_cause_hint']}")
    return "\n".join(lines)


def check_network_events():
    now = datetime.now()
    with get_db() as conn:
        events = [dict(r) for r in conn.execute(
            "SELECT * FROM network_events ORDER BY COALESCE(start_time, '') DESC LIMIT 200"
        ).fetchall()]

    fired = 0
    for ev in events:
        start = _parse_ts(ev["start_time"])
        if start is None:
            continue

        # ── 恢复 ──
        if ev["end_time"]:
            # 恢复事件：本地 id 作为键，保证一次事件只推一次
            key = f"network_recovered_{ev['local_id']}"
            if _recently_alerted(ev["agent_id"], key, 86400):
                continue
            end = _parse_ts(ev["end_time"])
            duration = ev["duration_seconds"]
            if duration is None and end:
                duration = int((end - start).total_seconds())
            duration = int(duration or 0)
            alerter.dispatch(
                key, ev["agent_id"],
                f"【{_agent_label(ev['agent_id'])}】网络已恢复\n"
                f"中断时长：{duration // 60} 分 {duration % 60} 秒"
                + (f"\n根因：{ev['root_cause_hint']}" if ev.get("root_cause_hint") else ""),
                "warning",
            )
            fired += 1
            continue

        # ── 还在断 ──
        duration = int((now - start).total_seconds())
        if duration < config.OFFLINE_ALERT_AFTER_SECONDS:
            continue

        first_key = f"network_offline_{ev['local_id']}"
        remind_key = f"network_offline_remind_{ev['local_id']}"

        if _recently_alerted(ev["agent_id"], first_key, 86400):
            # 首次已报过：只有「已持续超过提醒间隔」且「上次提醒也在一个间隔之前」
            # 才追一条，否则下一轮就会立刻追（实测踩过这个坑）
            if (duration >= config.OFFLINE_REMIND_SECONDS
                    and not _recently_alerted(ev["agent_id"], remind_key,
                                              config.OFFLINE_REMIND_SECONDS)):
                alerter.dispatch(remind_key, ev["agent_id"],
                                 "仍在中断中\n" + _event_message(ev, duration),
                                 "error")
                fired += 1
            continue

        alerter.dispatch(first_key, ev["agent_id"], _event_message(ev, duration), "error")
        fired += 1

    if fired:
        logger.warning("[看门狗] 断线/恢复告警 %d 条", fired)


def run_watchdog():
    """单轮执行，异常不外抛（看门狗自身不能把调度器带崩）"""
    for fn in (check_agent_silence, check_network_events):
        try:
            fn()
        except Exception as e:
            logger.error("[看门狗] %s 异常: %s", fn.__name__, e, exc_info=True)


# ── 生命周期 ───────────────────────────────────────────────────

_watchdog_scheduler = BackgroundScheduler()


def start_watchdog():
    if _watchdog_scheduler.running:
        return
    _watchdog_scheduler.add_job(
        run_watchdog,
        trigger=IntervalTrigger(seconds=config.WATCHDOG_INTERVAL_SECONDS),
        id=_WATCHDOG_JOB_ID,
        replace_existing=True,
    )
    _watchdog_scheduler.start()
    logger.info(
        "[看门狗] 已启动，每 %d 秒检查一次（失联阈值 %d 秒 / 断线告知 %d 秒）",
        config.WATCHDOG_INTERVAL_SECONDS,
        config.AGENT_SILENCE_SECONDS,
        config.OFFLINE_ALERT_AFTER_SECONDS,
    )


def stop_watchdog():
    if _watchdog_scheduler.running:
        _watchdog_scheduler.shutdown(wait=False)
        logger.info("[看门狗] 已停止")
