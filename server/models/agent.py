from pydantic import BaseModel
from typing import Optional


class AgentRegister(BaseModel):
    agent_id: str
    name: Optional[str] = ""
    ip: Optional[str] = ""
    os_type: Optional[str] = ""
    interval: Optional[int] = 60


class AgentInfo(BaseModel):
    agent_id: str
    name: str
    ip: str
    os_type: str
    interval: int
    last_seen: Optional[str] = None
    online: bool = False


class AgentRegisterResponse(BaseModel):
    success: bool
    message: str
    agent_token: str
    interval: int
