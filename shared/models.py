"""Shared Pydantic models and enums used across Aegis microservices."""
from __future__ import annotations

import enum
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class EventType(str, enum.Enum):
    DOCUMENT_WRITE = "document.write"
    DOCUMENT_READ  = "document.read"
    FINANCIAL_TX   = "financial.tx"
    USER_LOGIN     = "user.login"
    USER_LOGOUT    = "user.logout"
    MODULE_INIT    = "module.init"
    MODULE_USE     = "module.use"
    SECURITY_ALERT = "security.alert"
    FREEZE_TRIGGER = "freeze.trigger"
    MESH_MESSAGE   = "mesh.message"
    VDI_SESSION    = "vdi.session"


class SeverityLevel(str, enum.Enum):
    INFO     = "info"
    WARNING  = "warning"
    CRITICAL = "critical"
    FATAL    = "fatal"


class AegisEvent(BaseModel):
    id:         UUID
    type:       EventType
    source:     str
    actor:      Optional[str]   = None
    payload:    dict[str, Any]  = Field(default_factory=dict)
    timestamp:  datetime        = Field(default_factory=datetime.utcnow)
    signature:  Optional[str]   = None


class SecurityAlert(BaseModel):
    id:           UUID
    severity:     SeverityLevel
    title:        str
    description:  str
    source_event: Optional[UUID] = None
    score:        float          = 0.0
    timestamp:    datetime       = Field(default_factory=datetime.utcnow)
    resolved:     bool           = False


class TokenClaim(BaseModel):
    module_id:    str
    tenant_id:    str
    event_type:   str
    issued_at:    float
    nonce:        str
    signature:    str


class HealthResponse(BaseModel):
    service:  str
    status:   str = "ok"
    version:  str = "1.0.0"
    uptime:   float
