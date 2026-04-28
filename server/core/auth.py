from fastapi import HTTPException, Header
from typing import Optional
from core.database import get_db


def verify_agent_token(authorization: Optional[str] = Header(None)) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="缺少 Authorization header")
    parts = authorization.split(" ")
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Authorization 格式错误，应为：Bearer <token>")
    token = parts[1]
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT agent_id FROM agents WHERE token = ?", (token,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=401, detail="无效的 token")
        return row["agent_id"]


def verify_admin_password(x_password: Optional[str] = Header(None)) -> bool:
    from .config import config
    if not x_password or x_password != config.ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="管理员密码错误")
    return True
