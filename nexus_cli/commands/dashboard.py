"""``nexus dashboard`` — launch the local browser control panel (PRD §10, §13).

Starts the FastAPI backend, the Next.js frontend, and (best-effort) a
`kubectl port-forward` to Grafana as subprocesses, waits for the backend to
be ready, then opens the browser with a fresh per-session token in the URL.
Ctrl+C tears all of them down cleanly.
"""

from __future__ import annotations

import subprocess
import webbrowser

import typer

from nexus_cli.core import dashboard as core_dashboard
from nexus_cli.core import kubectl, output


def dashboard() -> None:
    """Launch the dashboard backend + frontend and open it in your browser."""
    try:
        core_dashboard.check_dashboard_deps_installed()
        core_dashboard.check_backend_source_present()
        core_dashboard.check_frontend_ready()
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
    procs.append(core_dashboard.start_frontend())

    grafana_proc = core_dashboard.start_grafana_port_forward()
    if grafana_proc is not None:
        procs.append(grafana_proc)
        output.step(f"Port-forwarding Grafana -> http://localhost:{core_dashboard.GRAFANA_LOCAL_PORT}")
    else:
        output.step("No Grafana found on the cluster — its panel will show setup instructions.")

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
