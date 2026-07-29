"""Launch/teardown logic for ``nexus dashboard`` (PRD §10, §13).

No Typer here — this is the reusable half (preflight checks, process
launch, health poll, shutdown), so it can be unit-tested without going
through the CLI. The command module owns option parsing and printing.

One subprocess, not two: the frontend is a static export (``next build``
with ``NEXUS_STATIC_EXPORT=1``, see ``dashboard/frontend/next.config.ts``)
that ``dashboard/backend/main.py`` serves itself alongside its own ``/api/*``
routes. This is what makes ``pip install nexus-gitops[dashboard]`` work on a
machine with no Node installed — Node/npm are a *maintainer*-time
requirement (building the wheel, see ``hatch_build.py``), not a user one.
Before this, ``dashboard/frontend`` shipped as source only and needed its own
``npm run dev`` process; that workflow still exists for frontend development
(see ``dashboard/frontend/README.md``), it's just no longer what ``nexus
dashboard`` itself launches.
"""

from __future__ import annotations

import importlib.util
import os
import secrets
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from nexus_cli.core import kubectl
from nexus_cli.core.output import NexusError

BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 3002
BACKEND_READY_TIMEOUT = 15
SHUTDOWN_GRACE_PERIOD = 5
TOKEN_ENV_VAR = "NEXUS_DASHBOARD_TOKEN"
# The directory `nexus dashboard` was launched from — normally the one
# containing the app's own nexus.yaml and git checkout, same convention every
# other command follows. The backend's own process cwd is fixed to
# `repo_root()` (it needs to import `dashboard.backend.main` as a module), so
# without this it has no way to find the app's repo for commit-message
# lookups (core.git.commit_subject) in the GitOps Log.
APP_REPO_DIR_ENV_VAR = "NEXUS_APP_REPO_DIR"

# Must match deploy.py's PROM_RELEASE ("kube-prom-stack") — the
# kube-prometheus-stack chart names its Grafana Service "<release>-grafana"
# and its Prometheus Service "<release>-kube-prome-prometheus".
GRAFANA_NAMESPACE = "monitoring"
GRAFANA_SERVICE = "kube-prom-stack-grafana"
GRAFANA_LOCAL_PORT = 3000
GRAFANA_REMOTE_PORT = 80

PROMETHEUS_NAMESPACE = "monitoring"
PROMETHEUS_SERVICE = "kube-prom-stack-kube-prome-prometheus"
PROMETHEUS_LOCAL_PORT = 9090
PROMETHEUS_REMOTE_PORT = 9090


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


def check_frontend_built() -> None:
    """The frontend ships as a static export (``out/``), not source that
    needs npm at runtime — see this module's docstring. A release wheel
    bundles it (``hatch_build.py``); a repo checkout needs one manual
    ``npm run build`` before the first ``nexus dashboard``.
    """
    if not (frontend_dir() / "out" / "index.html").is_file():
        raise NexusError(
            what="Dashboard frontend isn't built.",
            why=f"Expected {frontend_dir() / 'out'} — not present.",
            fix=(
                "If you installed a release wheel this shouldn't happen — please file a bug. "
                f"From a repo checkout, run: cd {frontend_dir()} && "
                "NEXUS_STATIC_EXPORT=1 npm ci && NEXUS_STATIC_EXPORT=1 npm run build"
            ),
        )


def generate_token() -> str:
    return secrets.token_urlsafe(32)


def start_backend(token: str) -> subprocess.Popen[bytes]:
    env = {**os.environ, TOKEN_ENV_VAR: token, APP_REPO_DIR_ENV_VAR: os.getcwd()}
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


def service_available(service: str, namespace: str) -> bool:
    """Whether a Service exists to port-forward to.

    Best-effort: kubectl missing, cluster unreachable, or the component never
    installed all just mean "nothing to forward to" here — none of that
    should stop ``nexus dashboard`` itself from starting, since callers
    (Metrics panel, sparklines) already degrade gracefully on their own when
    there's nothing listening on the other end.
    """
    try:
        kubectl.get_json("svc", namespace=namespace, name=service)
    except NexusError:
        return False
    return True


def start_port_forward(
    service: str, namespace: str, local_port: int, remote_port: int
) -> subprocess.Popen[bytes] | None:
    """``kubectl port-forward`` to a Service, or ``None`` if it doesn't exist.

    Used for both Grafana and Prometheus so the dashboard's Metrics panel and
    sparklines work out of the box instead of requiring the user to run this
    command themselves in another terminal. If the local port is already
    taken (another instance, a manual port-forward already running),
    kubectl's own error prints directly since output isn't captured; callers'
    own reachability checks still degrade gracefully either way.
    """
    if not service_available(service, namespace):
        return None
    return subprocess.Popen(
        [
            "kubectl",
            "port-forward",
            f"svc/{service}",
            f"{local_port}:{remote_port}",
            "-n",
            namespace,
        ],
        start_new_session=True,
    )


def grafana_available() -> bool:
    return service_available(GRAFANA_SERVICE, GRAFANA_NAMESPACE)


def start_grafana_port_forward() -> subprocess.Popen[bytes] | None:
    return start_port_forward(
        GRAFANA_SERVICE, GRAFANA_NAMESPACE, GRAFANA_LOCAL_PORT, GRAFANA_REMOTE_PORT
    )


def prometheus_available() -> bool:
    return service_available(PROMETHEUS_SERVICE, PROMETHEUS_NAMESPACE)


def start_prometheus_port_forward() -> subprocess.Popen[bytes] | None:
    return start_port_forward(
        PROMETHEUS_SERVICE, PROMETHEUS_NAMESPACE, PROMETHEUS_LOCAL_PORT, PROMETHEUS_REMOTE_PORT
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
    return f"http://localhost:{BACKEND_PORT}/?token={token}"


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
    "APP_REPO_DIR_ENV_VAR",
    "BACKEND_HOST",
    "BACKEND_PORT",
    "GRAFANA_LOCAL_PORT",
    "GRAFANA_NAMESPACE",
    "GRAFANA_SERVICE",
    "PROMETHEUS_LOCAL_PORT",
    "PROMETHEUS_NAMESPACE",
    "PROMETHEUS_SERVICE",
    "TOKEN_ENV_VAR",
    "backend_dir",
    "check_backend_source_present",
    "check_dashboard_deps_installed",
    "check_frontend_built",
    "dashboard_url",
    "frontend_dir",
    "generate_token",
    "grafana_available",
    "prometheus_available",
    "repo_root",
    "service_available",
    "shutdown",
    "start_backend",
    "start_grafana_port_forward",
    "start_port_forward",
    "start_prometheus_port_forward",
    "wait_for_backend_ready",
]
