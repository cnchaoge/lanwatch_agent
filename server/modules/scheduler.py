"""定时探测调度器，基于 APScheduler"""
import json
from typing import Optional, Dict, List, Any
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.jobstores.memory import MemoryJobStore
from core.database import get_db
from core.config import config


class ProbeScheduler:
    """探测任务调度器单例"""

    def __init__(self):
        self.scheduler = BackgroundScheduler(
            jobstores={"default": MemoryJobStore()},
            timezone="Asia/Shanghai",
        )

    # ----------------------------------------------------------------- life

    def start(self):
        if not self.scheduler.running:
            self.scheduler.start()

    def shutdown(self):
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    # ------------------------------------------------------------ job control

    def add_job(self, job_id: str, agent_id: str, probe_type: str,
                target: str, interval_seconds: int = 300, enabled: bool = True,
                name: str = ""):
        with get_db() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO scheduler_jobs "
                "(job_id, agent_id, probe_type, target, interval_seconds, enabled, name) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (job_id, agent_id, probe_type, target, interval_seconds,
                 1 if enabled else 0, name),
            )
        if enabled:
            self.scheduler.add_job(
                self._execute_probe,
                trigger=IntervalTrigger(seconds=interval_seconds),
                id=job_id,
                args=[job_id, agent_id, probe_type, target],
                replace_existing=True,
            )

    def add_probe_job(self, agent_id: str, probe_type: str,
                       target: str, interval_seconds: int = 300):
        """按 agent+type+target 生成 job_id 并注册（方便 SNMP 管理器调用）"""
        job_id = f"{agent_id}:{probe_type}:{target}"
        self.add_job(job_id, agent_id, probe_type, target, interval_seconds)

    def remove_probe_job(self, agent_id: str, probe_type: str, target: str):
        """按 agent+type+target 生成 job_id 并移除"""
        job_id = f"{agent_id}:{probe_type}:{target}"
        self.remove_job(job_id)

    def remove_job(self, job_id: str):
        with get_db() as conn:
            conn.execute("DELETE FROM scheduler_jobs WHERE job_id = ?", (job_id,))
        try:
            self.scheduler.remove_job(job_id)
        except Exception:
            pass

    def get_jobs(self) -> List[Dict[str, Any]]:
        jobs: List[Dict[str, Any]] = []
        with get_db() as conn:
            cur = conn.execute(
                "SELECT * FROM scheduler_jobs ORDER BY created_at DESC")
            for row in cur.fetchall():
                info = dict(row)
                try:
                    aps = self.scheduler.get_job(row["job_id"])
                    info["next_run_time"] = (
                        aps.next_run_time.isoformat()
                        if aps and aps.next_run_time
                        else None
                    )
                except Exception:
                    info["next_run_time"] = None
                jobs.append(info)
        return jobs

    def run_job_now(self, job_id: str) -> bool:
        with get_db() as conn:
            cur = conn.execute(
                "SELECT * FROM scheduler_jobs WHERE job_id = ?", (job_id,))
            row = cur.fetchone()
            if not row:
                return False
            self._execute_probe(
                row["job_id"], row["agent_id"],
                row["probe_type"], row["target"],
            )
            return True

    def reload_jobs_from_db(self):
        self.scheduler.remove_all_jobs()
        with get_db() as conn:
            cur = conn.execute(
                "SELECT * FROM scheduler_jobs WHERE enabled = 1")
            for row in cur.fetchall():
                self.scheduler.add_job(
                    self._execute_probe,
                    trigger=IntervalTrigger(seconds=row["interval_seconds"]),
                    id=row["job_id"],
                    args=[row["job_id"], row["agent_id"],
                          row["probe_type"], row["target"]],
                    replace_existing=True,
                )

    # -------------------------------------------------------- probe execution

    def _execute_probe(self, job_id: str, agent_id: str,
                       probe_type: str, target: str):
        from modules.alerter import alerter

        result: dict = {}
        try:
            if probe_type == "ping":
                from modules.ping import ping_host
                result = ping_host(target, count=config.PING_COUNT)
            elif probe_type == "traceroute":
                from modules.traceroute import traceroute
                hops = traceroute(target, max_hops=config.TRACEROUTE_MAX_HOPS)
                result = {"target": target, "hops": hops,
                          "hop_count": len(hops)}
            elif probe_type == "portscan":
                from modules.portscan import scan_common_ports
                result = {"host": target, "results": scan_common_ports(target)}
            elif probe_type == "dns":
                from modules.dns_test import test_dns
                result = test_dns(target)
            elif probe_type == "http":
                from modules.http_check import check_url
                result = check_url(target)
            elif probe_type == "snmp":
                from modules.snmp_manager import snmp_manager
                result = snmp_manager.collect_snmp_metrics(agent_id, target)
        except Exception as exc:
            result = {"status": "error", "error": str(exc)}

        rtt = result.get("avg_rtt") if probe_type == "ping" else None
        if probe_type == "ping":
            status = "ok" if result.get("status") == "ok" else "error"
        elif probe_type == "http":
            status = "ok" if result.get("reachable") else "error"
        elif probe_type == "traceroute":
            status = "ok" if result.get("hop_count", 0) > 0 else "error"
        elif probe_type == "snmp":
            status = "ok" if result.get("success") else "error"
        elif probe_type == "dns":
            status = "ok" if result.get("dns_ms") is not None else "error"
        elif probe_type == "portscan":
            status = "ok" if result.get("results") else "error"
        else:
            status = "ok" if result.get("status") != "error" else "error"

        with get_db() as conn:
            conn.execute(
                "INSERT INTO probe_results "
                "(agent_id, probe_type, target, status, rtt_ms, raw_output) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (agent_id, probe_type, target, status, rtt,
                 json.dumps(result)),
            )

        # 告警评估
        if probe_type == "ping":
            alerter.evaluate_ping_result(agent_id, result)
        elif probe_type == "traceroute":
            alerter.evaluate_traceroute_result(agent_id, result)
        elif probe_type == "dns":
            alerter.evaluate_dns_result(agent_id, result)
        elif probe_type == "http":
            alerter.evaluate_http_result(agent_id, result)
        elif probe_type == "portscan":
            alerter.evaluate_portscan_result(agent_id, result)


scheduler = ProbeScheduler()
