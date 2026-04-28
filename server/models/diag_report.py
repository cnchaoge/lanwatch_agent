from pydantic import BaseModel
from typing import Optional, List, Dict, Any


class DiagResult(BaseModel):
    type: str
    target: str
    status: str
    details: Optional[Dict[str, Any]] = None


class DiagReportRequest(BaseModel):
    triggered_by: Optional[str] = None
    results: List[DiagResult]
    agent_diag_time: Optional[str] = None


class DiagReportResponse(BaseModel):
    success: bool
    message: str
    report_id: Optional[int] = None
