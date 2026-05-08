"""Basit token-bazlı auth — admin endpoint'ler için.

Token `.env`'den (`PA_ADMIN_TOKEN`) okunur. Yoksa admin endpoint'leri 503 döner
(deliberate fail-closed). Tek geliştirici / küçük ekip için yeterli; multi-user
LDAP / OAuth2 sonraki faz.
"""
from __future__ import annotations

import os
from typing import Annotated

from fastapi import Header, HTTPException, status

from price_action.logging_config import logger


def _expected_token() -> str | None:
    return os.getenv("PA_ADMIN_TOKEN") or None


def verify_token(
    x_admin_token: Annotated[str | None, Header(alias="X-Admin-Token")] = None,
) -> str:
    """`Depends(verify_token)` ile admin endpoint'lerine bağlanır."""
    expected = _expected_token()
    if not expected:
        logger.warning("auth.no_admin_token_configured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="admin auth not configured (set PA_ADMIN_TOKEN)",
        )
    if not x_admin_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing X-Admin-Token header",
        )
    if not _safe_compare(x_admin_token, expected):
        logger.warning("auth.bad_token")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="invalid token",
        )
    return x_admin_token


def _safe_compare(a: str, b: str) -> bool:
    """Sabit zamanlı karşılaştırma."""
    if len(a) != len(b):
        return False
    out = 0
    for x, y in zip(a, b, strict=False):
        out |= ord(x) ^ ord(y)
    return out == 0
