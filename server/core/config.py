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

    @classmethod
    def get_cors_origins(cls):
        if not cls.CORS_ORIGINS:
            return []
        return cls.CORS_ORIGINS


config = Config()
