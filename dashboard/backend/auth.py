"""Per-session token auth for mutating dashboard endpoints (PRD §13).

A malicious web page open in the user's browser could POST directly to
``http://127.0.0.1:3002`` — browsers restrict a page from *reading* a
cross-origin response, not from *sending* one (local CSRF). Every mutating
endpoint therefore requires a bearer token that ``nexus dashboard`` generates
fresh per session and passes to this process only via an environment
variable, never written to disk.

Read-only GET endpoints are deliberately NOT gated: PRD §13 scopes the token
requirement to mutating endpoints only, and gating reads too would force the
token through every page load for no security benefit (nothing in this
dashboard is sensitive to read on localhost).
"""

from __future__ import annotations

import os
import secrets

from fastapi import Header, HTTPException

TOKEN_ENV_VAR = "NEXUS_DASHBOARD_TOKEN"


def require_token(authorization: str | None = Header(default=None)) -> None:
    """FastAPI dependency: 401 on a missing/wrong token, 503 if unconfigured.

    The 503 case (no token set on the backend at all) is kept distinct from
    401 — it means the backend wasn't launched via ``nexus dashboard``, which
    is a setup problem the caller can't fix by supplying a better header.
    """
    expected = os.environ.get(TOKEN_ENV_VAR)
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="Dashboard token not configured on the backend.",
        )
    provided = (authorization or "").removeprefix("Bearer ").strip()
    if not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Missing or invalid dashboard token.")
