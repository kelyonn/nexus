"""``nexus dashboard``'s local FastAPI backend (PRD §10, §11, §13).

Launched by ``nexus_cli.commands.dashboard`` as ``uvicorn
dashboard.backend.main:app --host 127.0.0.1 --port 3002`` — bound to
loopback only, since this is a local developer tool never meant to be
reachable from another device on the network (PRD §13). CORS is scoped to
the Next.js dev server's own origin rather than ``*``, for the same reason.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from dashboard.backend.routes import router

# Both spellings of loopback: the dev server binds 127.0.0.1 but the browser is
# opened at localhost, and those are *different* origins to a browser. Requests
# normally reach this process via Next's same-origin /api/* rewrite so CORS
# never applies — but if that rewrite is bypassed or changed, allowing only one
# spelling would fail in a way that's tedious to diagnose.
FRONTEND_ORIGINS = ["http://localhost:3001", "http://127.0.0.1:3001"]

app = FastAPI(title="Nexus Dashboard API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)
app.include_router(router)


@app.get("/health")
def health() -> dict[str, bool]:
    """Polled by ``nexus dashboard`` to know the backend is ready before
    opening the browser — not part of the PRD §10 API surface itself.
    """
    return {"ok": True}
