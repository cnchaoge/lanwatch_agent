import sqlite3, os
from contextlib import contextmanager
from core.config import config


@contextmanager
def get_db():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
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
        CREATE TABLE IF NOT EXISTS agents (id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id TEXT UNIQUE NOT NULL, name TEXT DEFAULT '', ip TEXT DEFAULT '', os_type TEXT DEFAULT '', token TEXT DEFAULT '', secret_key TEXT, interval INTEGER DEFAULT 60, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, last_seen TIMESTAMP);
        CREATE TABLE IF NOT EXISTS snmp_devices (id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id TEXT NOT NULL, ip TEXT NOT NULL, port INTEGER DEFAULT 161, community TEXT DEFAULT 'public', snmp_version TEXT DEFAULT '2c', description TEXT, device_name TEXT DEFAULT '', device_type TEXT DEFAULT 'router', status TEXT DEFAULT 'unknown', last_poll INTEGER, snmpv3_username TEXT DEFAULT '', snmpv3_auth_protocol TEXT DEFAULT 'MD5', snmpv3_auth_key TEXT DEFAULT '', snmpv3_priv_protocol TEXT DEFAULT 'DES', snmpv3_priv_key TEXT DEFAULT '', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(agent_id, ip));
        CREATE TABLE IF NOT EXISTS snmp_metrics (id INTEGER PRIMARY KEY AUTOINCREMENT, device_ip TEXT NOT NULL, oid TEXT NOT NULL, value TEXT, raw_hex TEXT, raw_len INTEGER, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS probe_results (id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id TEXT NOT NULL, probe_type TEXT NOT NULL, target TEXT NOT NULL, status TEXT, rtt_ms REAL, raw_output TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS topology_nodes (id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id TEXT, ip TEXT UNIQUE NOT NULL, mac TEXT, hostname TEXT, device_type TEXT, vendor TEXT, raw_data TEXT, last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS topology_links (id INTEGER PRIMARY KEY AUTOINCREMENT, node_a_ip TEXT NOT NULL, node_a_port TEXT, node_b_ip TEXT NOT NULL, node_b_port TEXT, link_type TEXT, last_confirmed TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS diag_reports (id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id TEXT NOT NULL, report_json TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS alert_log (id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id TEXT NOT NULL, alert_type TEXT NOT NULL, message TEXT, level TEXT DEFAULT 'warning', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS scheduler_jobs (id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT UNIQUE NOT NULL, agent_id TEXT NOT NULL, probe_type TEXT NOT NULL, target TEXT NOT NULL, interval_seconds INTEGER DEFAULT 300, enabled INTEGER DEFAULT 1, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS agent_metrics (id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id TEXT NOT NULL, metric_key TEXT NOT NULL, metric_value REAL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE INDEX IF NOT EXISTS idx_probe_results_agent_type ON probe_results(agent_id, probe_type);
        CREATE INDEX IF NOT EXISTS idx_probe_results_created ON probe_results(created_at);
        CREATE INDEX IF NOT EXISTS idx_snmp_metrics_device_time ON snmp_metrics(device_ip, timestamp);
        CREATE INDEX IF NOT EXISTS idx_alert_log_agent_time ON alert_log(agent_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_topology_nodes_ip ON topology_nodes(ip);
        CREATE INDEX IF NOT EXISTS idx_diag_reports_agent_time ON diag_reports(agent_id, created_at);
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
        # 检查并添加 SNMP v3 列（迁移兼容）
        cursor.execute("PRAGMA table_info(snmp_devices)")
        snmp_cols = [row[1] for row in cursor.fetchall()]
        for col in ["snmpv3_username", "snmpv3_auth_protocol", "snmpv3_auth_key", "snmpv3_priv_protocol", "snmpv3_priv_key"]:
            if col not in snmp_cols:
                cursor.execute(f"ALTER TABLE snmp_devices ADD COLUMN {col} TEXT DEFAULT ''")
        # 迁移兼容：检查新增列
        for col in ["device_name", "device_type", "status", "last_poll"]:
            if col not in snmp_cols:
                default = "''" if col != "last_poll" else "NULL"
                if col == 'last_poll':
                    cursor.execute(f"ALTER TABLE snmp_devices ADD COLUMN {col} INTEGER")
                else:
                    cursor.execute(f"ALTER TABLE snmp_devices ADD COLUMN {col} TEXT DEFAULT ''")
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
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(agent_id, target, probe_type)
                )
            """)
            conn.commit()
        # 检查并添加 agents user_id 列（迁移兼容，预留多用户）
        cursor.execute("PRAGMA table_info(agents)")
        agent_cols = [row[1] for row in cursor.fetchall()]
        if "user_id" not in agent_cols:
            cursor.execute("ALTER TABLE agents ADD COLUMN user_id TEXT DEFAULT ''")
        conn.commit()
    finally:
        conn.close()
