"""``nexus open`` — port-forward the app's Service and open it in your
browser, until Ctrl+C (PRD §7.4-adjacent: same shape as ``nexus watch``).

``nexus deploy`` deliberately doesn't do this itself: it's a one-shot,
idempotent command, and a background tunnel left running after it exits
would collide with a later re-deploy on the same local port, with no
lifecycle anyone's tracking. This command exists so viewing the app is still
one command, just a separate, explicit one you run (and stop) on purpose —
`deploy`'s own "Access your app" message points here.
"""

from __future__ import annotations

import socket
import time
import webbrowser

import typer

from nexus_cli.core import config as nexus_config
from nexus_cli.core import dashboard as core_dashboard
from nexus_cli.core import output, preflight

LOCAL_PORT = 18080
REMOTE_PORT = 80
READY_TIMEOUT = 10


def _wait_for_port(port: int, *, timeout: int) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            time.sleep(0.3)
    return False


def open(
    config_path: str = typer.Option(
        "nexus.yaml", "--config", help="Path to the nexus.yaml to read."
    ),
) -> None:
    """Port-forward the app's Service and open it in your browser, until Ctrl+C."""
    try:
        preflight.ensure_cluster_ready(require_helm=False)
        cfg = nexus_config.load(config_path)
    except output.NexusError as err:
        output.print_error(err)
        raise typer.Exit(code=1) from err

    name = cfg.app.name
    proc = core_dashboard.start_port_forward(name, name, LOCAL_PORT, REMOTE_PORT)
    if proc is None:
        missing_svc_err = output.NexusError(
            what=f"Service '{name}' not found in namespace '{name}'.",
            fix="Run `nexus deploy` first, or check `nexus status`.",
        )
        output.print_error(missing_svc_err)
        raise typer.Exit(code=1)

    url = f"http://127.0.0.1:{LOCAL_PORT}"
    output.step(f"Port-forwarding {name} -> {url}")
    if not _wait_for_port(LOCAL_PORT, timeout=READY_TIMEOUT):
        not_ready_err = output.NexusError(
            what=f"Port-forward to svc/{name} did not become ready within {READY_TIMEOUT}s.",
            fix=(
                f"Run `kubectl -n {name} port-forward svc/{name} {LOCAL_PORT}:{REMOTE_PORT}` "
                "directly to see the real error."
            ),
        )
        output.print_error(not_ready_err)
        core_dashboard.shutdown(proc)
        raise typer.Exit(code=1)

    output.success(f"Opening {url} — Ctrl+C to stop.")
    webbrowser.open(url)
    try:
        proc.wait()
    except KeyboardInterrupt:
        pass
    finally:
        output.step("")
        output.step("Shutting down...")
        core_dashboard.shutdown(proc)
