"""
配置管理：
- 配置文件路径：%PROGRAMDATA%\\LanwatchAgent\\config.json
- 支持热重载（发送 reload 信号）
"""
import os, json, pathlib
from typing import Optional, Dict, Any

PROGRAM_DATA = os.environ.get("PROGRAMDATA", "C:\\ProgramData")
CONFIG_DIR = os.path.join(PROGRAM_DATA, "LanwatchAgent")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
LOG_FILE = os.path.join(CONFIG_DIR, "agent.log")

DEFAULT_CONFIG = {
    "server_url": "http://localhost:8000",
    "agent_id": "",
    "agent_name": "",
    "agent_ip": "",
    "agent_os": "windows",
    "agent_token": "",
    "probe_interval": 60,
    "enabled_probes": ["ping"],
    "log_level": "INFO",
    "auto_update": False
}


class Config:
    """全局配置对象（单例）"""
    _instance = None
    _data: Dict[str, Any] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load()
        return cls._instance

    def _load(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    self._data = {**DEFAULT_CONFIG, **loaded}
            except Exception:
                self._data = DEFAULT_CONFIG.copy()
        else:
            self._data = DEFAULT_CONFIG.copy()

    def reload(self):
        """重新从磁盘加载配置"""
        self._load()

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def set(self, key: str, value):
        self._data[key] = value

    def save(self):
        """保存配置到磁盘"""
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=4, ensure_ascii=False)

    def as_dict(self) -> Dict[str, Any]:
        return self._data.copy()

    @property
    def server_url(self) -> str:
        return self._data.get("server_url", "http://localhost:8000")

    @property
    def agent_id(self) -> str:
        return self._data.get("agent_id", "")

    @property
    def agent_token(self) -> str:
        return self._data.get("agent_token", "")

    @property
    def probe_interval(self) -> int:
        return self._data.get("probe_interval", 60)

    @property
    def enabled_probes(self) -> list:
        return self._data.get("enabled_probes", ["ping"])

    @property
    def log_level(self) -> str:
        return self._data.get("log_level", "INFO")


def load_config() -> Config:
    return Config()


def save_config(cfg: Config):
    cfg.save()


def ensure_config_dir():
    """确保配置目录存在"""
    os.makedirs(CONFIG_DIR, exist_ok=True)


def get_log_path() -> str:
    return LOG_FILE
