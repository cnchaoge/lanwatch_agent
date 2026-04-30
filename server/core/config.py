import os


class Config:
    SCKEY = os.environ.get("SCKEY", "")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin")
    DB_PATH = os.environ.get("DB_PATH", "monitor.db")
    _cors_origins = os.environ.get("CORS_ORIGINS", "")
    CORS_ORIGINS = [o.strip() for o in _cors_origins.split(",") if o.strip()] if _cors_origins else []
    AGENT_TOKEN_LENGTH = 32
    AGENT_DEFAULT_INTERVAL = 60
    PING_TIMEOUT = 4
    PING_COUNT = 4
    TRACEROUTE_MAX_HOPS = 30
    TRACEROUTE_TIMEOUT = 3
    ALERT_COOLDOWN_SECONDS = 300
    DINGTALK_WEBHOOK = os.environ.get("DINGTALK_WEBHOOK", "")
    FEISHU_WEBHOOK = os.environ.get("FEISHU_WEBHOOK", "")

    # 数据保留天数
    RETENTION_PROBE_DAYS = int(os.environ.get("RETENTION_PROBE_DAYS", "5"))
    RETENTION_SNMP_DAYS = int(os.environ.get("RETENTION_SNMP_DAYS", "5"))
    RETENTION_ALERT_DAYS = int(os.environ.get("RETENTION_ALERT_DAYS", "30"))
    RETENTION_DIAG_DAYS = int(os.environ.get("RETENTION_DIAG_DAYS", "30"))

    @classmethod
    def get_cors_origins(cls):
        if not cls.CORS_ORIGINS:
            return []
        return cls.CORS_ORIGINS


config = Config()
