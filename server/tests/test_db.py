"""数据库操作单元测试"""
import pytest, sys, os, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.database import get_db, init_db
import core.database


@pytest.fixture(autouse=True)
def _isolated_db():
    """每个测试使用独立的临时数据库"""
    db_path = tempfile.mktemp(suffix=".db")
    old_path = core.database.config.DB_PATH
    core.database.config.DB_PATH = db_path
    yield
    core.database.config.DB_PATH = old_path
    try:
        os.unlink(db_path)
    except OSError:
        pass


def test_init_db():
    """数据库初始化"""
    init_db()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cursor.fetchall()]
        assert "agents" in tables
        assert "probe_results" in tables
        assert "snmp_devices" in tables
        assert "topology_nodes" in tables
        assert "diag_reports" in tables


def test_agent_crud():
    """Agent CRUD 操作"""
    init_db()
    with get_db() as conn:
        cursor = conn.cursor()
        # 插入
        cursor.execute("INSERT INTO agents (agent_id, name, ip, token) VALUES (?, ?, ?, ?)",
                       ("test-001", "测试", "192.168.1.1", "tok123"))
        # 查询
        cursor.execute("SELECT * FROM agents WHERE agent_id=?", ("test-001",))
        row = cursor.fetchone()
        assert row is not None
        assert row["name"] == "测试"
        assert row["token"] == "tok123"
        # 更新
        cursor.execute("UPDATE agents SET name=? WHERE agent_id=?", ("新名称", "test-001"))
        cursor.execute("SELECT name FROM agents WHERE agent_id=?", ("test-001",))
        assert cursor.fetchone()["name"] == "新名称"
        # 删除
        cursor.execute("DELETE FROM agents WHERE agent_id=?", ("test-001",))
        cursor.execute("SELECT * FROM agents WHERE agent_id=?", ("test-001",))
        assert cursor.fetchone() is None


def test_probe_results():
    """探测结果写入"""
    init_db()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO agents (agent_id, name) VALUES (?, ?)",
                       ("probe-test", "测试"))
        cursor.execute("""INSERT INTO probe_results (agent_id, probe_type, target, status, rtt_ms)
                           VALUES (?, ?, ?, ?, ?)""",
                       ("probe-test", "ping", "8.8.8.8", "ok", 50.5))
        cursor.execute("SELECT * FROM probe_results WHERE agent_id=?", ("probe-test",))
        row = cursor.fetchone()
        assert row is not None
        assert row["probe_type"] == "ping"
        assert row["rtt_ms"] == 50.5


def test_token_column_migration():
    """agents 表 token 列迁移"""
    import sqlite3
    # 手动建一个没有 token 列的旧表
    db_path = tempfile.mktemp(suffix=".db")
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE agents (id INTEGER PRIMARY KEY, agent_id TEXT UNIQUE, name TEXT)")
    conn.close()

    # 切换到旧数据库
    old_path = core.database.config.DB_PATH
    core.database.config.DB_PATH = db_path
    try:
        core.database.init_db()
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT token FROM agents LIMIT 1")
    finally:
        core.database.config.DB_PATH = old_path
        os.unlink(db_path)
