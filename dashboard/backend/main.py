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

FRONTEND_ORIGIN = "http://localhost:3001"

app = FastAPI(title="Nexus Dashboard API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN],
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
