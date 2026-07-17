"""``nexus status`` — deployment health at a glance (PRD §7.3).

Reads the Deployment's replica counts, the ArgoCD Application's sync/health
status, and each pod's phase — surfacing ImagePullBackOff/CrashLoopBackOff
with a context-aware fix suggestion (Minikube vs. a real registry).
"""

from __future__ import annotations

from dataclasses import dataclass

import typer

from nexus_cli.core import argocd, kubectl, output, preflight
from nexus_cli.core import config as nexus_config

_IMAGE_PULL_REASONS = {"ImagePullBackOff", "ErrImagePull"}
_CRASH_REASONS = {"CrashLoopBackOff"}


@dataclass(frozen=True)
class PodInfo:
    name: str
    phase: str
    restarts: int
    problem: str | None


def _pod_problem(pod: dict) -> str | None:
    for cs in pod.get("status", {}).get("containerStatuses", []):
        reason = cs.get("state", {}).get("waiting", {}).get("reason")
        if reason in _IMAGE_PULL_REASONS or reason in _CRASH_REASONS:
            return str(reason)
    return None


def _pod_restarts(pod: dict) -> int:
    statuses = pod.get("status", {}).get("containerStatuses", [])
    return sum(cs.get("restartCount", 0) for cs in statuses)


def list_pods(namespace: str) -> list[PodInfo]:
    """Pods in the app's namespace (one app per namespace — no selector needed)."""
    doc = kubectl.get_json("pods", namespace=namespace)
    pods = []
    for item in doc.get("items", []):
        pods.append(
            PodInfo(
                name=item["metadata"]["name"],
                phase=item.get("status", {}).get("phase", "Unknown"),
                restarts=_pod_restarts(item),
                problem=_pod_problem(item),
            )
        )
    return pods


def replica_counts(namespace: str, name: str) -> tuple[int, int]:
    """(desired, available) replica counts for the app's Deployment."""
    doc = kubectl.get_json("deployment", namespace=namespace, name=name)
    desired = doc.get("spec", {}).get("replicas", 0)
    available = doc.get("status", {}).get("availableReplicas", 0)
    return desired, available


def image_pull_fix() -> str:
    """Context-aware fix suggestion for ImagePullBackOff (PRD §7.2)."""
    context = kubectl.current_context() or ""
    if "minikube" in context.lower():
        return "Run `minikube image load <image>` to make the image visible to the cluster."
    return "Push the image to a registry the cluster can reach (Docker Hub, GHCR, ECR, etc.)."


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

    output.step("")
    output.step(f"Nexus Status — {name}")
    output.step("-" * 43)

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
        if pod.problem in _IMAGE_PULL_REASONS:
            output.warn(f"    {pod.problem}: image cannot be pulled.")
            output.step(f"    Fix: {image_pull_fix()}")
        elif pod.problem in _CRASH_REASONS:
            output.warn(f"    {pod.problem}: container is crashing on start.")
            output.step(f"    Fix: check `kubectl -n {namespace} logs {pod.name}` for the error.")
