"""
network_monitor stub — v1.3.0
旧版本地 SQLite 事件库已废弃（监控逻辑迁移至 TargetRunner）。
本文件仅提供 UI 历史记录页需要的最小 API，数据改由服务端 API 获取。
"""
import os

EVENTS_DB = os.path.join(
    os.environ.get("PROGRAMDATA", "C:\\ProgramData"),
    "LanwatchAgent", "network_events.db"
)


def query_events(limit=50, offset=0):
    """查询网络事件（现为空，服务端接管）"""
    return []


def count_events():
    """统计事件数量（现为0）"""
    return 0


def get_db():
    """保留入口，调用者应改用服务端 API"""
    return None
