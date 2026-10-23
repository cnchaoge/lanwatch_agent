import sqlite3, os
import logging
from datetime import datetime
from contextlib import contextmanager

logger = logging.getLogger("database")
from core.config import config


def local_now() -> str:
    """本地时间字符串，格式与 SQLite datetime() 一致。

    业务代码算时间边界一律用它，不要依赖 CURRENT_TIMESTAMP（那是 UTC），
    否则与 datetime.now() 差一个时区，历史/趋势查询窗口会错位。
    """
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@contextmanager
def get_db():
    # timeout=30 + WAL：
    # 服务端有多个并发写入方（Agent 上报、看门狗、探测调度器、数据清理），
    # 默认 rollback journal 模式下「写锁阻塞所有读」，busy_timeout 只有 5 秒，
    # 一撞上就是 OperationalError: database is locked（2026-10-23 实测复现）。
    # WAL 允许读写并发，NORMAL 在 WAL 下也够安全且快很多。
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA synchronous=NORMAL")
    except sqlite3.DatabaseError:
        # 老库切 WAL 可能失败（并发中/只读目录），不阻断业务
        pass
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    db_dir = os.path.dirname(config.DB_PATH)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir)
    conn = sqlite3.connect(config.DB_PATH)
    try:
        cursor = conn.cursor()
        sql = """
        CREATE TABLE IF NOT EXISTS agents (id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id TEXT UNIQUE NOT NULL, name TEXT DEFAULT '', ip TEXT DEFAULT '', os_type TEXT DEFAULT '', token TEXT DEFAULT '', secret_key TEXT, interval INTEGER DEFAULT 60, created_at TIMESTAMP DEFAULT (datetime('now','localtime')), last_seen TIMESTAMP);
        CREATE TABLE IF NOT EXISTS probe_results (id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id TEXT NOT NULL, probe_type TEXT NOT NULL, target TEXT NOT NULL, status TEXT, rtt_ms REAL, raw_output TEXT, created_at TIMESTAMP DEFAULT (datetime('now','localtime')));
        CREATE TABLE IF NOT EXISTS topology_nodes (id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id TEXT, ip TEXT UNIQUE NOT NULL, mac TEXT, hostname TEXT, device_type TEXT, vendor TEXT, raw_data TEXT, last_seen TIMESTAMP DEFAULT (datetime('now','localtime')));
        CREATE TABLE IF NOT EXISTS topology_links (id INTEGER PRIMARY KEY AUTOINCREMENT, node_a_ip TEXT NOT NULL, node_a_port TEXT, node_b_ip TEXT NOT NULL, node_b_port TEXT, link_type TEXT, last_confirmed TIMESTAMP DEFAULT (datetime('now','localtime')));
        CREATE TABLE IF NOT EXISTS diag_reports (id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id TEXT NOT NULL, report_json TEXT NOT NULL, created_at TIMESTAMP DEFAULT (datetime('now','localtime')));
        CREATE TABLE IF NOT EXISTS network_events (id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id TEXT NOT NULL, local_id INTEGER, event_type TEXT NOT NULL, start_time TEXT, end_time TEXT, duration_seconds INTEGER, gateway TEXT, error_message TEXT, hop_count INTEGER, diag_conclusion TEXT, root_cause_hint TEXT, synced_at TIMESTAMP, created_at TIMESTAMP DEFAULT (datetime('now','localtime')), UNIQUE(agent_id, local_id));
        CREATE TABLE IF NOT EXISTS alert_log (id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id TEXT NOT NULL, alert_type TEXT NOT NULL, message TEXT, level TEXT DEFAULT 'warning', created_at TIMESTAMP DEFAULT (datetime('now','localtime')));
        CREATE TABLE IF NOT EXISTS scheduler_jobs (id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT UNIQUE NOT NULL, agent_id TEXT NOT NULL, probe_type TEXT NOT NULL, target TEXT NOT NULL, interval_seconds INTEGER DEFAULT 300, enabled INTEGER DEFAULT 1, created_at TIMESTAMP DEFAULT (datetime('now','localtime')));
        CREATE TABLE IF NOT EXISTS agent_metrics (id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id TEXT NOT NULL, metric_key TEXT NOT NULL, metric_value REAL, created_at TIMESTAMP DEFAULT (datetime('now','localtime')));
        CREATE INDEX IF NOT EXISTS idx_probe_results_agent_type ON probe_results(agent_id, probe_type);
        CREATE INDEX IF NOT EXISTS idx_probe_results_created ON probe_results(created_at);
        CREATE INDEX IF NOT EXISTS idx_alert_log_agent_time ON alert_log(agent_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_topology_nodes_ip ON topology_nodes(ip);
        CREATE INDEX IF NOT EXISTS idx_diag_reports_agent_time ON diag_reports(agent_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_network_events_agent_time ON network_events(agent_id, start_time);
        CREATE INDEX IF NOT EXISTS idx_agent_metrics_key_time ON agent_metrics(agent_id, metric_key, created_at);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_agents_name ON agents(name) WHERE name != '';
        """
        cursor.executescript(sql)
        conn.commit()
        # 检查并添加 token 列（迁移兼容）
        cursor.execute("PRAGMA table_info(agents)")
        cols = [row[1] for row in cursor.fetchall()]
        if "token" not in cols:
            cursor.execute("ALTER TABLE agents ADD COLUMN token TEXT DEFAULT ''")
            conn.commit()
        # 检查并添加 agents phone 列（迁移兼容）
        cursor.execute("PRAGMA table_info(agents)")
        agent_cols = [row[1] for row in cursor.fetchall()]
        if "phone" not in agent_cols:
            cursor.execute("ALTER TABLE agents ADD COLUMN phone TEXT DEFAULT ''")
        # 检查并添加 scheduler_jobs name 列（迁移兼容）
        cursor.execute("PRAGMA table_info(scheduler_jobs)")
        sched_cols = [row[1] for row in cursor.fetchall()]
        if "name" not in sched_cols:
            cursor.execute("ALTER TABLE scheduler_jobs ADD COLUMN name TEXT DEFAULT ''")
        # 检查并添加 targets 表（v1.3.0 新增）
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='targets'")
        if not cursor.fetchone():
            cursor.execute("""
                CREATE TABLE targets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id TEXT NOT NULL,
                    name TEXT DEFAULT '',
                    target TEXT NOT NULL,
                    probe_type TEXT NOT NULL,
                    port INTEGER DEFAULT 80,
                    timeout INTEGER DEFAULT 5,
                    interval INTEGER DEFAULT 60,
                    enabled INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT (datetime('now','localtime')),
                    UNIQUE(agent_id, target, probe_type)
                )
            """)
            conn.commit()

        # 检查并添加 chat_logs 表（v1.3.1：AI 数字分身聊天记录）
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='chat_logs'")
        if not cursor.fetchone():
            cursor.execute("CREATE TABLE chat_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL, created_at TIMESTAMP DEFAULT (datetime('now','localtime')))")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_chat_logs_session ON chat_logs(session_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_chat_logs_time ON chat_logs(created_at)")
            conn.commit()

        # 检查并添加 agents user_id 列（迁移兼容，预留多用户）
        cursor.execute("PRAGMA table_info(agents)")
        agent_cols = [row[1] for row in cursor.fetchall()]
        if "user_id" not in agent_cols:
            cursor.execute("ALTER TABLE agents ADD COLUMN user_id TEXT DEFAULT ''")
        conn.commit()
    finally:
        conn.close()
