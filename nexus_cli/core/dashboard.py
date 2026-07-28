"""Launch/teardown logic for ``nexus dashboard`` (PRD §10, §13).

No Typer here — this is the reusable half (preflight checks, process
launch, health poll, shutdown), so it can be unit-tested without going
through the CLI. The command module owns option parsing and printing.

**Known gap, documented rather than hidden:** ``dashboard/backend`` and
``dashboard/frontend`` ship as plain source in the repo, not inside the
installable wheel (see ``pyproject.toml``'s wheel packaging — only
``nexus_cli`` is a package). So this only works from a checkout of the Nexus
repository itself, not from a bare ``pip install nexus-gitops[dashboard]``.
That's a real limitation, not an oversight: bundling a prebuilt Next.js
frontend into a Python wheel is a separate piece of work, tracked as a
follow-up rather than solved here.
"""

from __future__ import annotations

import importlib.util
import os
import secrets
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from nexus_cli.core.output import NexusError

BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 3002
FRONTEND_PORT = 3001
BACKEND_READY_TIMEOUT = 15
SHUTDOWN_GRACE_PERIOD = 5
TOKEN_ENV_VAR = "NEXUS_DASHBOARD_TOKEN"


def repo_root() -> Path:
    """The Nexus repo checkout this package was loaded from."""
    return Path(__file__).resolve().parents[2]


def backend_dir() -> Path:
    return repo_root() / "dashboard" / "backend"


def frontend_dir() -> Path:
    return repo_root() / "dashboard" / "frontend"


def check_dashboard_deps_installed() -> None:
    """fastapi/uvicorn are an optional extra, not a core dependency."""
    missing = [name for name in ("fastapi", "uvicorn") if importlib.util.find_spec(name) is None]
    if missing:
        raise NexusError(
            what=f"Missing dashboard dependencies: {', '.join(missing)}.",
            why="fastapi/uvicorn are an optional extra, not part of the base install.",
            fix='Run `pip install "nexus-gitops[dashboard]"`.',
        )


def check_backend_source_present() -> None:
    if not (backend_dir() / "main.py").is_file():
        raise NexusError(
            what="Dashboard backend source not found.",
            why=(
                f"Expected {backend_dir()} — this feature currently requires a checkout "
                "of the Nexus repository, not just a pip install."
            ),
            fix="Clone https://github.com/kelyonn/nexus and run `nexus dashboard` from inside it.",
        )


def check_frontend_ready() -> None:
    if shutil.which("npm") is None:
        raise NexusError(
            what="npm is required but not installed.",
            fix="Install Node.js (which bundles npm): https://nodejs.org/",
        )
    if not (frontend_dir() / "node_modules").is_dir():
        raise NexusError(
            what="Dashboard frontend dependencies aren't installed.",
            fix=f"Run `npm install` in {frontend_dir()}.",
        )


def generate_token() -> str:
    return secrets.token_urlsafe(32)


def start_backend(token: str) -> subprocess.Popen[bytes]:
    env = {**os.environ, TOKEN_ENV_VAR: token}
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "dashboard.backend.main:app",
            "--host",
            BACKEND_HOST,
            "--port",
            str(BACKEND_PORT),
        ],
        cwd=str(repo_root()),
        env=env,
        # Its own session so a Ctrl+C in the terminal doesn't also deliver
        # SIGINT to this child directly — shutdown() below is the one thing
        # that signals it, so there's exactly one shutdown path, not a race
        # between the terminal's signal fan-out and our own cleanup.
        start_new_session=True,
    )


def start_frontend() -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        ["npm", "run", "dev"],
        cwd=str(frontend_dir()),
        start_new_session=True,
    )


def wait_for_backend_ready(*, timeout: int = BACKEND_READY_TIMEOUT) -> None:
    """Poll the backend's /health until it responds, or raise on timeout."""
    url = f"http://{BACKEND_HOST}:{BACKEND_PORT}/health"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1):  # noqa: S310 - fixed localhost URL
                return
        except (urllib.error.URLError, OSError):
            time.sleep(0.5)
    raise NexusError(
        what=f"Dashboard backend did not become ready within {timeout}s.",
        fix="Check the backend's own output above for the actual startup error.",
    )


def dashboard_url(token: str) -> str:
    return f"http://localhost:{FRONTEND_PORT}/?token={token}"


def _signal_group(proc: subprocess.Popen[bytes], sig: int) -> None:
    try:
        os.killpg(proc.pid, sig)
    except ProcessLookupError:
        pass  # already gone


def shutdown(*processes: subprocess.Popen[bytes]) -> None:
    """Terminate child processes cleanly: SIGTERM, a bounded wait, then SIGKILL.

    Signals the whole process group, not just the immediate child — npm's
    `run dev` spawns `next dev` as its own child process, and
    ``start_new_session=True`` at launch made each of these its own group
    leader (pgid == pid), so killing only the direct child would leave that
    grandchild (and Next's Turbopack workers) orphaned.
    """
    for proc in processes:
        if proc.poll() is None:
            _signal_group(proc, signal.SIGTERM)
    deadline = time.monotonic() + SHUTDOWN_GRACE_PERIOD
    for proc in processes:
        remaining = max(0.0, deadline - time.monotonic())
        try:
            proc.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            _signal_group(proc, signal.SIGKILL)
            proc.wait()


__all__ = [
    "BACKEND_HOST",
    "BACKEND_PORT",
    "FRONTEND_PORT",
    "TOKEN_ENV_VAR",
    "backend_dir",
    "check_backend_source_present",
    "check_dashboard_deps_installed",
    "check_frontend_ready",
    "dashboard_url",
    "frontend_dir",
    "generate_token",
    "repo_root",
    "shutdown",
    "start_backend",
    "start_frontend",
    "wait_for_backend_ready",
]
