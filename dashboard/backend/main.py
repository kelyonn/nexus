"""``nexus dashboard``'s local FastAPI backend (PRD §10, §11, §13).

Launched by ``nexus_cli.commands.dashboard`` as ``uvicorn
dashboard.backend.main:app --host 127.0.0.1 --port 3002`` — bound to
loopback only, since this is a local developer tool never meant to be
reachable from another device on the network (PRD §13).

This process serves the frontend too: ``dashboard/frontend`` builds to a
static export (see ``static.py``), so one backend process is the whole
dashboard — no Next.js runtime, no Node needed on the end user's machine.
CORS is now mostly a fallback rather than the primary path (everything is
same-origin once the frontend and API share a port), but stays scoped to
loopback's two spellings rather than ``*``, for the same reason as before:
this is a local developer tool never meant to be reachable from another
device on the network.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from dashboard.backend import static
from dashboard.backend.routes import router

# Both spellings of loopback are different origins to a browser. Same-origin
# requests (the normal case, now that the frontend and API share a port)
# never hit CORS at all — this only matters if something fetches across the
# two spellings directly.
FRONTEND_ORIGINS = ["http://localhost:3002", "http://127.0.0.1:3002"]

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


# Must be registered last: FastAPI/Starlette match routes in registration
# order, not by specificity, and this router's `/{full_path:path}` would
# otherwise swallow `/health` and every `/api/*` route above it.
app.include_router(static.router)
