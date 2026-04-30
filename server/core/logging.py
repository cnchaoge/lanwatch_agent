"""统一日志配置"""
import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler


_LOG_CONFIGURED = False


def setup_logging(log_dir: str = "logs", log_level: str = "INFO",
                  max_bytes: int = 10 * 1024 * 1024, backup_count: int = 5):
    global _LOG_CONFIGURED
    if _LOG_CONFIGURED:
        return
    _LOG_CONFIGURED = True

    level = getattr(logging, log_level.upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(level)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-5s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # always log to stdout
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)

    # file handler with rotation
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        str(log_path / "lanwatch.log"),
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    # quiet noisy libs
    for lib in ("uvicorn.access", "apscheduler.scheduler", "httpx"):
        logging.getLogger(lib).setLevel(logging.WARNING)
