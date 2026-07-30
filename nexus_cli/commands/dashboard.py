"""``nexus dashboard`` — launch the local browser control panel (PRD §10, §13).

Starts the FastAPI backend (which serves the frontend's static export
itself, see core/dashboard.py's docstring) and (best-effort) `kubectl
port-forward`s to Grafana and Prometheus as subprocesses, waits for the
backend to be ready, then opens the browser with a fresh per-session token
in the URL. Ctrl+C tears all of them down cleanly.
"""

from __future__ import annotations

import subprocess
import webbrowser
from collections.abc import Callable

import typer

from nexus_cli.core import dashboard as core_dashboard
from nexus_cli.core import kubectl, output


def _start_optional_port_forward(
    procs: list[subprocess.Popen[bytes]],
    *,
    label: str,
    start_fn: Callable[[], subprocess.Popen[bytes] | None],
    local_port: int,
) -> None:
    """Best-effort port-forward: on success, track it for shutdown() and tell
    the user; on failure (component not installed), say so and move on —
    every consumer of these (Metrics panel, sparklines) already degrades
    gracefully when there's nothing listening.
    """
    proc = start_fn()
    if proc is not None:
        procs.append(proc)
        output.step(f"Port-forwarding {label} -> http://localhost:{local_port}")
    else:
        output.step(f"No {label} found on the cluster — related panels will show as unavailable.")


def dashboard() -> None:
    """Launch the local dashboard and open it in your browser."""
    try:
        core_dashboard.check_dashboard_deps_installed()
        core_dashboard.check_backend_source_present()
        core_dashboard.check_frontend_built()
        if not kubectl.cluster_reachable():
            raise output.NexusError(
                what="No reachable Kubernetes cluster.",
                fix="Start your cluster (e.g. `minikube start`) and retry.",
            )
    except output.NexusError as err:
        output.print_error(err)
        raise typer.Exit(code=1) from err

    token = core_dashboard.generate_token()
    procs: list[subprocess.Popen[bytes]] = []

    output.step("Starting dashboard backend...")
    backend_proc = core_dashboard.start_backend(token)
    procs.append(backend_proc)

    _start_optional_port_forward(
        procs,
        label="Grafana",
        start_fn=core_dashboard.start_grafana_port_forward,
        local_port=core_dashboard.GRAFANA_LOCAL_PORT,
    )
    _start_optional_port_forward(
        procs,
        label="Prometheus",
        start_fn=core_dashboard.start_prometheus_port_forward,
        local_port=core_dashboard.PROMETHEUS_LOCAL_PORT,
    )

    try:
        core_dashboard.wait_for_backend_ready()
    except output.NexusError as err:
        output.print_error(err)
        core_dashboard.shutdown(*procs)
        raise typer.Exit(code=1) from err

    url = core_dashboard.dashboard_url(token)
    output.success(f"Dashboard ready — opening {url}")
    output.step("Press Ctrl+C to stop.")
    webbrowser.open(url)

    try:
        backend_proc.wait()
    except KeyboardInterrupt:
        pass
    finally:
        output.step("")
        output.step("Shutting down...")
        core_dashboard.shutdown(*procs)
