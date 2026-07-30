"""``nexus destroy`` — remove an app's resources, not shared platform
components (PRD §7.5, §8).

Requires typing the app's name to confirm (not just y/N — this is
destructive and hard to reverse). Idempotent: safe to run when some or all
of the resources are already gone (``kubectl.delete`` treats "not found" and
"resource type not installed" both as success — see core/kubectl.py).

``--dry-run`` is a second, cheaper safety net on top of the typed-name
confirmation: it prints exactly the same resource list the real run would
show, then stops before the prompt. That list is derived purely from
``nexus.yaml`` (what *would* be targeted), not from checking what actually
exists in the cluster — same as the real run's own pre-confirmation
listing always has been, so this doesn't change what that block means, just
adds a way to see it without being asked to type the app name afterward.
"""

from __future__ import annotations

from collections.abc import Callable

import typer

from nexus_cli.core import config as nexus_config
from nexus_cli.core import kubectl, output, preflight
from nexus_cli.core.config import NexusConfig


def _remove_namespace(name: str) -> None:
    """Deletes the app's whole namespace — which also takes its ServiceMonitor
    (PRD §10.4) and its imagePullSecret (core/registry.py) with it, since both
    live in the app's own namespace, not ``monitoring``. Unlike the
    PrometheusRules/Grafana ConfigMap below, no separate teardown step is
    needed for either.
    """
    kubectl.delete("namespace", name)


def _remove_argocd_app(name: str) -> None:
    kubectl.delete("application", name, namespace="argocd")


def _remove_monitoring(name: str) -> None:
    kubectl.delete("prometheusrule", f"{name}-availability", namespace="monitoring")
    kubectl.delete("prometheusrule", f"{name}-restarts", namespace="monitoring")
    kubectl.delete("configmap", f"{name}-grafana-dashboards", namespace="monitoring")


def _remove_chaos(name: str) -> None:
    kubectl.delete("schedule", f"{name}-chaos-schedule", namespace="chaos-mesh")


def destroy_steps(cfg: NexusConfig) -> list[tuple[str, Callable[[], None]]]:
    name = cfg.app.name
    steps: list[tuple[str, Callable[[], None]]] = [
        (f"Removing namespace {name}...", lambda: _remove_namespace(name)),
        ("Removing ArgoCD app...", lambda: _remove_argocd_app(name)),
    ]
    if cfg.platform.monitoring:
        steps.append(("Removing monitoring resources...", lambda: _remove_monitoring(name)))
    if cfg.platform.chaos:
        steps.append(("Removing chaos schedule...", lambda: _remove_chaos(name)))
    return steps


def _print_resource_list(cfg: NexusConfig) -> None:
    name = cfg.app.name
    output.step("The following resources will be permanently deleted:")
    output.step("")
    output.step(f"  Namespace:         {name} (and all pods, services inside)")
    output.step(f"  ArgoCD App:        {name}")
    if cfg.platform.monitoring:
        output.step(f"  PrometheusRules:   {name}-availability, {name}-restarts")
        output.step(f"  Grafana Dashboard: {name}-grafana-dashboards")
    if cfg.app.registry is not None:
        output.step(f"  imagePullSecret:   {cfg.app.registry_secret_name}")
    if cfg.platform.chaos:
        output.step(f"  Chaos Schedule:    {name}-chaos-schedule")
    output.step("")
    output.step("ArgoCD, Prometheus, and Chaos Mesh will NOT be removed.")


def destroy(
    config_path: str = typer.Option(
        "nexus.yaml", "--config", help="Path to the nexus.yaml to read."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would be deleted without deleting anything."
    ),
) -> None:
    """Remove this app's namespace, ArgoCD Application, and monitoring resources."""
    try:
        preflight.ensure_cluster_ready(require_helm=False)
        cfg = nexus_config.load(config_path)
    except output.NexusError as err:
        output.print_error(err)
        raise typer.Exit(code=1) from err

    name = cfg.app.name

    output.header(f"Nexus Destroy — {name}")
    _print_resource_list(cfg)
    output.step("")

    if dry_run:
        output.step("Dry run — nothing was deleted. Run without --dry-run to actually destroy.")
        return

    typed = typer.prompt(f"Type the app name to confirm ({name})")
    if typed != name:
        output.warn("Name did not match — aborted. Nothing was deleted.")
        raise typer.Exit(code=1)

    output.step("")
    steps = destroy_steps(cfg)
    total = len(steps)
    for i, (label, fn) in enumerate(steps, start=1):
        output.info(f"[{i}/{total}] {label}")
        try:
            fn()
        except output.NexusError as err:
            output.print_error(err)
            raise typer.Exit(code=1) from err
        output.success("    done")
        output.step("")

    output.success(f"{name} has been fully removed.")
