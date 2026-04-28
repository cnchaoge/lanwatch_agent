from pydantic import BaseModel
from typing import Optional, Any


class ProbeReport(BaseModel):
    probe_type: str
    target: str
    status: str
    rtt_ms: Optional[float] = None
    output: Optional[Any] = None
