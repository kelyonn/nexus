"""``nexus logs`` — pod logs for the app, prefixed by pod name (PRD §7.8).

Thin terminal wrapper: the SDK call and its bytes-decode workaround live in
``core/logs.py`` so the same fetch can serve non-CLI callers.
"""

from __future__ import annotations

import typer

from nexus_cli.core import config as nexus_config
from nexus_cli.core import logs as core_logs
from nexus_cli.core import output, preflight


def logs(
    config_path: str = typer.Option(
        "nexus.yaml", "--config", help="Path to the nexus.yaml to read."
    ),
    tail: int = typer.Option(
        core_logs.DEFAULT_TAIL, "--tail", help="Number of lines to show per pod."
    ),
) -> None:
    """Print each pod's log tail, prefixed with the pod name."""
    try:
        preflight.ensure_cluster_ready(require_helm=False)
        cfg = nexus_config.load(config_path)
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
