"""ArgoCD Application registration and status (PRD §7.2, §7.3, §9).

ArgoCD Applications are just a CRD, so registration and polling go through
``kubectl`` — no ``argocd`` CLI dependency. ``managed-by: nexus`` is set on
every Application by the render templates (PRD §10.1's app-discovery
mechanism for the dashboard).
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from nexus_cli.core import kubectl, status
from nexus_cli.core.output import NexusError

NAMESPACE = "argocd"
DEFAULT_POLL_INTERVAL = 3
DEFAULT_TIMEOUT = 180

MANAGED_BY_LABEL = "managed-by"
MANAGED_BY_VALUE = "nexus"


@dataclass(frozen=True)
class ArgoAppStatus:
    name: str
    sync_status: str  # "Synced" | "OutOfSync" | "Unknown"
    health_status: str  # "Healthy" | "Progressing" | "Degraded" | "Missing" | "Unknown"
    revision: str | None
    last_sync_time: str | None


@dataclass(frozen=True)
class SyncEvent:
    """One past sync recorded in the Application's history.

    ArgoCD's history entries carry a git revision and a deployment timestamp,
    but no per-entry success/failure marker or commit message — those would
    need a separate lookup against the app's own git repo. The dashboard's
    GitOps Log (PRD §10.3) pairs this with the Application's *current*
    sync/health status rather than inventing a per-event status ArgoCD
    doesn't actually report.
    """

    revision: str | None
    deployed_at: str | None


def register(rendered_yaml: str) -> None:
    """Apply an ArgoCD Application manifest. Idempotent (kubectl apply)."""
    kubectl.apply_manifest(rendered_yaml)


def _parse_status(doc: dict, name: str) -> ArgoAppStatus:
    """Pull the sync/health fields out of one Application document."""
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


def get_status(name: str) -> ArgoAppStatus | None:
    """Fetch an Application's status, or None if it doesn't exist yet."""
    try:
        doc = kubectl.get_json("application", namespace=NAMESPACE, name=name)
    except NexusError:
        return None
    return _parse_status(doc, name)


def list_managed_apps() -> list[ArgoAppStatus]:
    """Every Nexus-managed Application, sorted by name (PRD §10.1).

    This is the dashboard's app-discovery mechanism: the CLI operates on one
    app at a time, but every Application it registers carries the
    ``managed-by: nexus`` label (see ``templates/argocd-app.yaml.j2``), so
    listing by that label is what makes a multi-app overview possible.

    A cluster with no ArgoCD at all returns ``[]`` rather than raising — the
    Application CRD being absent is a legitimate "there are no Nexus apps"
    answer. Any *other* failure (cluster unreachable, RBAC denied) still
    raises, so a real problem is never silently reported as an empty list.
    """
    try:
        doc = kubectl.get_json("application", namespace=NAMESPACE)
    except NexusError as err:
        if kubectl.is_missing_resource_type(err.why or ""):
            return []
        raise

    apps = []
    for item in doc.get("items", []):
        metadata = item.get("metadata", {})
        labels = metadata.get("labels") or {}
        name = metadata.get("name")
        if name and labels.get(MANAGED_BY_LABEL) == MANAGED_BY_VALUE:
            apps.append(_parse_status(item, name))
    return sorted(apps, key=lambda app: app.name)


def sync_history(name: str) -> list[SyncEvent]:
    """Past syncs for one Application, most recent first.

    Empty if the Application doesn't exist or has never synced — both are
    ordinary states (a freshly registered app has no history yet), not errors.
    """
    try:
        doc = kubectl.get_json("application", namespace=NAMESPACE, name=name)
    except NexusError:
        return []
    history = doc.get("status", {}).get("history") or []
    events = [
        SyncEvent(revision=h.get("revision"), deployed_at=h.get("deployedAt")) for h in history
    ]
    return sorted(events, key=lambda e: e.deployed_at or "", reverse=True)


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


def _deployment_actually_ready(name: str) -> bool:
    """Ground truth from the Deployment itself, bypassing ArgoCD's own health check.

    Namespace and Deployment name both equal ``name`` — one app per namespace,
    same convention ``commands/status.py`` relies on.
    """
    try:
        desired, available = status.replica_counts(name, name)
    except NexusError:
        return False
    return desired > 0 and available >= desired


def wait_for_healthy(
    name: str,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    poll_interval: int = DEFAULT_POLL_INTERVAL,
) -> ArgoAppStatus:
    """Poll until the Application is Synced + Healthy, or raise on timeout.

    On ArgoCD v3.4.5 (currently the version ``nexus deploy`` installs),
    ``health`` can stay stuck on ``Progressing`` indefinitely for a Deployment
    Kubernetes itself reports fully available — an upstream health-check quirk
    on this resource/version, observed stable for 90+ seconds and unchanged by
    a manual hard-refresh (see docs/IMPLEMENTATION-PLAN.md Week 1 finding #3).
    Rather than have every ``deploy``/``upgrade``/``rollback`` time out and
    print a false failure for a rollout that actually succeeded, ``Synced`` +
    ``Progressing`` is accepted once the Deployment's own replica counts
    confirm it's really ready. ``Degraded``/``Missing`` are never overridden —
    those are ArgoCD reporting an actual problem, not a stale status.

    The returned status still carries ArgoCD's real (possibly ``Progressing``)
    ``health_status`` — this function decides whether to keep waiting, not
    what to claim happened. Callers that want to tell the user their own
    health check disagreed with ArgoCD's should check for that themselves.
    """
    deadline = time.monotonic() + timeout
    last: ArgoAppStatus | None = None
    while time.monotonic() < deadline:
        last = get_status(name)
        if last and last.sync_status == "Synced":
            if last.health_status == "Healthy":
                return last
            if last.health_status == "Progressing" and _deployment_actually_ready(name):
                return last
        time.sleep(poll_interval)
    detail = f"sync={last.sync_status}, health={last.health_status}" if last else "not found"
    raise NexusError(
        what=f"Application '{name}' did not become Synced + Healthy within {timeout}s.",
        why=f"Last observed status: {detail}.",
        fix=f"Run `kubectl -n {NAMESPACE} describe application {name}` to see what's blocking it.",
    )
