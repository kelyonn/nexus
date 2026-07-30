"""``nexus logs`` — pod logs for the app, prefixed by pod name (PRD §7.8).

Thin terminal wrapper: the SDK calls and their bytes-decode workaround live
in ``core/logs.py`` so the same fetch can serve non-CLI callers.
"""

from __future__ import annotations

import threading

import typer

from nexus_cli.core import config as nexus_config
from nexus_cli.core import logs as core_logs
from nexus_cli.core import output, preflight


def _run_follow(cfg: nexus_config.NexusConfig, tail: int) -> None:
    print_lock = threading.Lock()

    def _print_line(pod: str, line: str) -> None:
        # follow_pod_logs may call this from several pods' threads at
        # once — an unsynchronized output.step() here can interleave and
        # garble a line across threads.
        with print_lock:
            output.step(f"{pod} | {line}")

    output.step(f"Following logs for '{cfg.app.name}' — Ctrl+C to stop.")
    try:
        pod_names = core_logs.follow_pod_logs(
            cfg.app.name, cfg.app.name, tail=tail, on_line=_print_line
        )
    except output.NexusError as err:
        output.print_error(err)
        raise typer.Exit(code=1) from err
    except KeyboardInterrupt:
        output.step("")
        output.step("Stopped following.")
        return

    if not pod_names:
        output.warn(f"No pods found for '{cfg.app.name}'.")


def logs(
    config_path: str = typer.Option(
        "nexus.yaml", "--config", help="Path to the nexus.yaml to read."
    ),
    tail: int = typer.Option(
        core_logs.DEFAULT_TAIL, "--tail", help="Number of lines to show per pod."
    ),
    follow: bool = typer.Option(
        False, "--follow", "-f", help="Stream logs continuously until Ctrl+C."
    ),
) -> None:
    """Print each pod's log tail, prefixed with the pod name."""
    try:
        preflight.ensure_cluster_ready(require_helm=False)
        cfg = nexus_config.load(config_path)
    except output.NexusError as err:
        output.print_error(err)
        raise typer.Exit(code=1) from err

    if follow:
        _run_follow(cfg, tail)
        return

    try:
        pod_logs = core_logs.get_pod_logs(cfg.app.name, cfg.app.name, tail=tail)
    except output.NexusError as err:
        output.print_error(err)
        raise typer.Exit(code=1) from err

    if not pod_logs:
        output.warn(f"No pods found for '{cfg.app.name}'.")
        return

    for entry in pod_logs:
        if entry.error:
            output.warn(f"Could not fetch logs for {entry.pod}: {entry.error}")
            continue
        for line in entry.lines:
            output.step(f"{entry.pod} | {line}")
