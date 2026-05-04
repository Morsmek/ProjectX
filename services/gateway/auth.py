"""JWT + API-key authentication for the gateway."""
from __future__ import annotations

import hashlib
import hmac
import os
import time
from typing import Optional

from fastapi import HTTPException, Header, Request
from jose import JWTError, jwt

SECRET_KEY = os.environ.get("SECRET_KEY", "")
ALGORITHM  = "HS256"


def create_access_token(subject: str, tenant: str, roles: list[str], ttl: int = 3600) -> str:
    payload = {
        "sub":    subject,
        "tenant": tenant,
        "roles":  roles,
        "iat":    time.time(),
        "exp":    time.time() + ttl,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")


def validate_hermes_token(token: str, actor: str, resource: str) -> bool:
    """Verify a multi-sig read-authorization token issued by Hermes."""
    try:
        claims = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return (
            claims.get("actor") == actor
            and claims.get("resource") == resource
            and claims.get("purpose") == "authorized_read"
            and claims.get("exp", 0) > time.time()
        )
    except Exception:
        return False


def internal_key_guard(x_internal_key: str = Header(...)):
    if not hmac.compare_digest(x_internal_key, SECRET_KEY):
        raise HTTPException(status_code=403, detail="Forbidden")


def get_current_user(authorization: Optional[str] = Header(None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    return decode_token(authorization.split(" ", 1)[1])
