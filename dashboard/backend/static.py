"""Serves the frontend's static export (PRD §13 — pip-installable dashboard).

``dashboard/frontend`` builds to ``out/`` via ``next build`` with
``NEXUS_STATIC_EXPORT=1`` set (see ``next.config.ts`` and ``hatch_build.py``
at the repo root). This module mounts that directory behind a catch-all
route, implementing the exact resolution Next.js's own static-export
deployment guide recommends for any static host — nginx's ``try_files $uri
$uri.html $uri/index.html``, translated to Python — rather than depending on
some static-file library's particular opinion of "SPA mode", which this
project doesn't need and would rather not have to verify against.

Registration order matters: this router's ``/{full_path:path}`` catch-all
must be the LAST thing ``dashboard/backend/main.py`` adds to the app, or it
would swallow ``/health`` and ``/api/*`` too — FastAPI matches routes in
registration order, not by specificity.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter()

FRONTEND_OUT_DIR = Path(__file__).resolve().parent.parent / "frontend" / "out"


def resolve_static_file(path: str, *, root: Path = FRONTEND_OUT_DIR) -> Path | None:
    """``try_files $uri $uri.html $uri/index.html`` for a request path.

    Returns the file to serve, or ``None`` if nothing matches (caller serves
    ``404.html`` or a plain 404). Also refuses anything that would resolve
    outside ``root`` — FastAPI's path converter already normalizes ``..``
    segments before this runs, but this is cheap, easy-to-test insurance
    against ever serving a file from outside the export directory.
    """
    root_resolved = root.resolve()
    candidates = (
        [root / "index.html"]
        if path == ""
        else [
            root / path,
            root / f"{path}.html",
            root / path / "index.html",
        ]
    )
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved != root_resolved and root_resolved not in resolved.parents:
            continue
        if resolved.is_file():
            return resolved
    return None


@router.get("/{full_path:path}", include_in_schema=False)
def serve_static(full_path: str) -> FileResponse:
    # Reads the module global by name rather than relying on
    # resolve_static_file's default parameter (bound once at import time) —
    # this way tests can monkeypatch FRONTEND_OUT_DIR per-case.
    match = resolve_static_file(full_path, root=FRONTEND_OUT_DIR)
    if match is not None:
        return FileResponse(match)
    not_found = FRONTEND_OUT_DIR / "404.html"
    if not_found.is_file():
        return FileResponse(not_found, status_code=404)
    raise HTTPException(status_code=404, detail="Not found")
