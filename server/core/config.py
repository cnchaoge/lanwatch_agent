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
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
    DINGTALK_WEBHOOK = os.environ.get("DINGTALK_WEBHOOK", "")
    FEISHU_WEBHOOK = os.environ.get("FEISHU_WEBHOOK", "")
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
    LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
    LLM_API_BASE = os.environ.get("LLM_API_BASE", "")
    LLM_MODEL = os.environ.get("LLM_MODEL", "")

    # ── 对外展示信息（脱敏配置，避免硬编码隐私数据）──
    # 留空表示不显示该字段；模板中以 {{ config.FIELD_NAME }} 渲染
    CONTACT_PHONE = os.environ.get("CONTACT_PHONE", "")
    CONTACT_HOURS = os.environ.get("CONTACT_HOURS", "工作时间")
    WECHAT_QR_URL = os.environ.get("WECHAT_QR_URL", "")  # 微信二维码图片 URL，留空则不显示二维码
    OFFICIAL_WEBSITE = os.environ.get("OFFICIAL_WEBSITE", "https://github.com/cnchaoge/lanwatch_agent")
    SERVER_PUBLIC_URL = os.environ.get("SERVER_PUBLIC_URL", "")  # 营销页/FAQ 中展示的服务端地址，留空则用占位符

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
