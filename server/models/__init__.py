from pydantic import BaseModel
from typing import Optional, List, Any
from datetime import datetime


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
    agent_token: Optional[str] = ""
    interval: int = 60


class ProbeReport(BaseModel):
    probe_type: str
    target: str
    status: str
    rtt_ms: Optional[float] = None
    output: Optional[Any] = None


class DiagReportRequest(BaseModel):
    report_data: dict


class DiagReportResponse(BaseModel):
    success: bool
    message: str
