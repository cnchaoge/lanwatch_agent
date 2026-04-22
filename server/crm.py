"""
客户管理 CRM 模块
"""
import sqlite3
import time
from pathlib import Path
from typing import Optional
from fastapi import HTTPException

DB_PATH = Path(__file__).parent / "monitor.db"

def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def close_db(conn):
    if conn:
        conn.close()

def init_crm_db():
    """初始化客户表"""
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                company TEXT DEFAULT '',
                phone TEXT DEFAULT '',
                email TEXT DEFAULT '',
                address TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
        """)
        conn.commit()
        print("[CRM] initialized")
    finally:
        close_db(conn)

# ─── 数据模型 ────────────────────────────────────────────────────────────

class CustomerCreate:
    name: str
    company: str = ""
    phone: str = ""
    email: str = ""
    address: str = ""
    notes: str = ""

class CustomerUpdate:
    name: Optional[str] = None
    company: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    notes: Optional[str] = None

# ─── CRUD 操作 ───────────────────────────────────────────────────────────

def list_customers():
    conn = get_db()
    try:
        c = conn.execute("SELECT * FROM customers ORDER BY id DESC")
        return [dict(r) for r in c.fetchall()]
    finally:
        close_db(conn)

def get_customer(customer_id: int):
    conn = get_db()
    try:
        c = conn.execute("SELECT * FROM customers WHERE id=?", (customer_id,))
        row = c.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="客户不存在")
        return dict(row)
    finally:
        close_db(conn)

def create_customer(data: dict):
    conn = get_db()
    try:
        now = time.time()
        conn.execute("""
            INSERT INTO customers (name, company, phone, email, address, notes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data.get("name", "").strip(),
            data.get("company", "").strip(),
            data.get("phone", "").strip(),
            data.get("email", "").strip(),
            data.get("address", "").strip(),
            data.get("notes", "").strip(),
            now, now
        ))
        conn.commit()
        c = conn.execute("SELECT * FROM customers WHERE id=last_insert_rowid()")
        return dict(c.fetchone())
    finally:
        close_db(conn)

def update_customer(customer_id: int, data: dict):
    conn = get_db()
    try:
        c = conn.execute("SELECT id FROM customers WHERE id=?", (customer_id,))
        if not c.fetchone():
            raise HTTPException(status_code=404, detail="客户不存在")
        fields, values = [], []
        for key in ["name", "company", "phone", "email", "address", "notes"]:
            if key in data:
                fields.append(f"{key}=?")
                values.append(data[key].strip() if data[key] else "")
        if not fields:
            return get_customer(customer_id)
        fields.append("updated_at=?")
        values.append(time.time())
        values.append(customer_id)
        conn.execute("UPDATE customers SET " + ",".join(fields) + " WHERE id=?", values)
        conn.commit()
        return get_customer(customer_id)
    finally:
        close_db(conn)

def delete_customer(customer_id: int):
    conn = get_db()
    try:
        c = conn.execute("SELECT id FROM customers WHERE id=?", (customer_id,))
        if not c.fetchone():
            raise HTTPException(status_code=404, detail="客户不存在")
        conn.execute("DELETE FROM customers WHERE id=?", (customer_id,))
        conn.commit()
        return {"ok": True}
    finally:
        close_db(conn)