"""ArgoCD Application registration and status (PRD §7.2, §7.3, §9).

ArgoCD Applications are just a CRD, so registration and polling go through
``kubectl`` — no ``argocd`` CLI dependency. ``managed-by: nexus`` is set on
every Application by the render templates (PRD §10.1's app-discovery
mechanism for the dashboard).
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from nexus_cli.core import kubectl
from nexus_cli.core.output import NexusError

NAMESPACE = "argocd"
DEFAULT_POLL_INTERVAL = 3
DEFAULT_TIMEOUT = 180


@dataclass(frozen=True)
class ArgoAppStatus:
    name: str
    sync_status: str  # "Synced" | "OutOfSync" | "Unknown"
    health_status: str  # "Healthy" | "Progressing" | "Degraded" | "Missing" | "Unknown"
    revision: str | None
    last_sync_time: str | None


def register(rendered_yaml: str) -> None:
    """Apply an ArgoCD Application manifest. Idempotent (kubectl apply)."""
    kubectl.apply_manifest(rendered_yaml)


def get_status(name: str) -> ArgoAppStatus | None:
    """Fetch an Application's status, or None if it doesn't exist yet."""
    try:
        doc = kubectl.get_json("application", namespace=NAMESPACE, name=name)
    except NexusError:
        return None
    status = doc.get("status", {})
    sync = status.get("sync", {})
    health = status.get("health", {})
    operation_state = status.get("operationState", {})
    return ArgoAppStatus(
        name=name,
        sync_status=sync.get("status", "Unknown"),
        health_status=health.get("status", "Unknown"),
        revision=sync.get("revision"),
        last_sync_time=operation_state.get("finishedAt"),
    )


def trigger_sync(name: str) -> None:
    """Ask ArgoCD to refresh + reconcile immediately, instead of waiting on its
    default poll interval (PRD §7.9/§7.10). No ``argocd`` CLI required — this
    patches the standard hard-refresh annotation that ArgoCD itself watches for.
    """
    kubectl.run(
        [
            "patch",
            "application",
            name,
            "-n",
            NAMESPACE,
            "--type",
            "merge",
            "-p",
            '{"metadata":{"annotations":{"argocd.argoproj.io/refresh":"hard"}}}',
        ]
    )


def wait_for_healthy(
    name: str,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    poll_interval: int = DEFAULT_POLL_INTERVAL,
) -> ArgoAppStatus:
    """Poll until the Application is Synced + Healthy, or raise on timeout."""
    deadline = time.monotonic() + timeout
    last: ArgoAppStatus | None = None
    while time.monotonic() < deadline:
        last = get_status(name)
        if last and last.sync_status == "Synced" and last.health_status == "Healthy":
            return last
        time.sleep(poll_interval)
    detail = f"sync={last.sync_status}, health={last.health_status}" if last else "not found"
    raise NexusError(
        what=f"Application '{name}' did not become Synced + Healthy within {timeout}s.",
        why=f"Last observed status: {detail}.",
        fix=f"Run `kubectl -n {NAMESPACE} describe application {name}` to see what's blocking it.",
    )
