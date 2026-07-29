"""Dashboard API routes (PRD §10 — Local Backend).

Every handler is a thin translation over ``nexus_cli.core`` — no cluster
logic lives here that isn't already in ``core/``, so the CLI and the
dashboard can never silently disagree about what a given app's status means.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from dashboard.backend.auth import require_token
from nexus_cli.core import argocd, kubectl
from nexus_cli.core import chaos as core_chaos
from nexus_cli.core import status as core_status
from nexus_cli.core.output import NexusError

router = APIRouter(prefix="/api")


class AppSummary(BaseModel):
    name: str
    sync_status: str
    health_status: str
    last_sync_time: str | None
    desired_replicas: int
    available_replicas: int


class PodSummary(BaseModel):
    name: str
    phase: str
    restarts: int
    problem: str | None
    created_at: str | None


class ChaosRequest(BaseModel):
    action: str = "pod-kill"
    kill_all: bool = False


class ChaosResponse(BaseModel):
    run_name: str


class SyncEventOut(BaseModel):
    revision: str | None
    deployed_at: str | None


class SyncLogResponse(BaseModel):
    app: str
    sync_status: str
    health_status: str
    last_sync_time: str | None
    history: list[SyncEventOut]


def _app_or_404(name: str) -> argocd.ArgoAppStatus:
    app_status = argocd.get_status(name)
    if app_status is None:
        raise HTTPException(status_code=404, detail=f"No Nexus-managed app named '{name}'.")
    return app_status


@router.get("/apps", response_model=list[AppSummary])
def list_apps() -> list[AppSummary]:
    """Overview grid data (PRD §10.1): one card per Nexus-managed app."""
    try:
        managed_apps = argocd.list_managed_apps()
    except NexusError as err:
        # A real failure here (cluster unreachable, RBAC denied) must reach the
        # user as a stated problem, not a bare 500 — PRD §12's what/why/fix bar
        # applies to this API too, not just the CLI's own error output.
        raise HTTPException(status_code=502, detail=str(err)) from err

    summaries = []
    for app in managed_apps:
        try:
            desired, available = core_status.replica_counts(app.name, app.name)
        except NexusError as err:
            # A Deployment that doesn't exist yet (registered with ArgoCD but
            # not synced) is an ordinary state — show the app with nothing
            # running. Anything else (RBAC denied, cluster unreachable) is a
            # real failure, and reporting it as "0 replicas" would be a lie
            # that looks exactly like a scaled-down app.
            if not kubectl.is_not_found(err.why or ""):
                raise HTTPException(status_code=502, detail=str(err)) from err
            desired, available = 0, 0
        summaries.append(
            AppSummary(
                name=app.name,
                sync_status=app.sync_status,
                health_status=app.health_status,
                last_sync_time=app.last_sync_time,
                desired_replicas=desired,
                available_replicas=available,
            )
        )
    return summaries


@router.get("/apps/{name}/pods", response_model=list[PodSummary])
def list_pods(name: str) -> list[PodSummary]:
    """Pod list for the App Detail view (PRD §10.2)."""
    _app_or_404(name)
    try:
        pods = core_status.list_pods(name)
    except NexusError as err:
        raise HTTPException(status_code=502, detail=str(err)) from err
    return [
        PodSummary(
            name=p.name, phase=p.phase, restarts=p.restarts, problem=p.problem,
            created_at=p.created_at,
        )
        for p in pods
    ]


@router.post(
    "/apps/{name}/chaos",
    response_model=ChaosResponse,
    dependencies=[Depends(require_token)],
)
def trigger_chaos(name: str, body: ChaosRequest) -> ChaosResponse:
    """"Trigger Chaos" button (PRD §10.2) — the one mutating endpoint."""
    _app_or_404(name)
    try:
        run_name = core_chaos.run_experiment(name, action=body.action, kill_all=body.kill_all)
    except NexusError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    return ChaosResponse(run_name=run_name)


@router.get("/apps/{name}/synclog", response_model=SyncLogResponse)
def sync_log(name: str) -> SyncLogResponse:
    """Recent ArgoCD sync events for one app (PRD §10.3)."""
    current = _app_or_404(name)
    history = argocd.sync_history(name)
    return SyncLogResponse(
        app=name,
        sync_status=current.sync_status,
        health_status=current.health_status,
        last_sync_time=current.last_sync_time,
        history=[SyncEventOut(revision=h.revision, deployed_at=h.deployed_at) for h in history],
    )
