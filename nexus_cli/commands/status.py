"""``nexus status`` — deployment health at a glance (PRD §7.3).

Reads the Deployment's replica counts, the ArgoCD Application's sync/health
status, and each pod's phase — surfacing ImagePullBackOff/CrashLoopBackOff
with a context-aware fix suggestion (Minikube vs. a real registry). The data
gathering lives in ``core/status.py`` so the dashboard can reuse it; this
module is just the terminal narration.
"""

from __future__ import annotations

import typer

from nexus_cli.core import argocd, kubectl, output, preflight
from nexus_cli.core import config as nexus_config
from nexus_cli.core.status import (
    CRASH_REASONS,
    IMAGE_PULL_REASONS,
    PodInfo,
    image_pull_fix,
    list_pods,
    replica_counts,
)

__all__ = [
    "PodInfo",
    "image_pull_fix",
    "list_pods",
    "replica_counts",
    "status",
]


def status(
    config_path: str = typer.Option(
        "nexus.yaml", "--config", help="Path to the nexus.yaml to read."
    ),
) -> None:
    """Show deployment health: replicas, ArgoCD sync/health, and pod status."""
    try:
        preflight.ensure_cluster_ready(require_helm=False)
        cfg = nexus_config.load(config_path)
    except output.NexusError as err:
        output.print_error(err)
        raise typer.Exit(code=1) from err

    name = cfg.app.name
    namespace = cfg.app.name

    output.header(f"Nexus Status — {name}")

    if not kubectl.namespace_exists(namespace):
        output.warn(f"Namespace '{namespace}' not found — has `nexus deploy` been run?")
        raise typer.Exit(code=1)

    try:
        desired, available = replica_counts(namespace, name)
    except output.NexusError as err:
        output.print_error(err)
        raise typer.Exit(code=1) from err

    output.step(f"App:        {name}")
    output.step(f"Namespace:  {namespace}")
    output.step(f"Replicas:   {available} / {desired}")

    app_status = argocd.get_status(name)
    if app_status:
        output.step(f"Sync:       {app_status.sync_status}")
        output.step(f"Health:     {app_status.health_status}")
        if app_status.last_sync_time:
            output.step(f"Last sync:  {app_status.last_sync_time}")
    else:
        output.step("Sync:       (not registered with ArgoCD)")

    output.step("")
    output.step("Pods:")
    pods = list_pods(namespace)
    if not pods:
        output.step("  (none)")
    for pod in pods:
        output.step(f"  {pod.name}  {pod.phase}  restarts={pod.restarts}")
        if pod.problem in IMAGE_PULL_REASONS:
            output.warn(f"    {pod.problem}: image cannot be pulled.")
            output.step(f"    Fix: {image_pull_fix(cfg.app.imagePullPolicy)}")
        elif pod.problem in CRASH_REASONS:
            output.warn(f"    {pod.problem}: container is crashing on start.")
            output.step(f"    Fix: check `kubectl -n {namespace} logs {pod.name}` for the error.")
