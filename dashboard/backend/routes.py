"""Dashboard API routes (PRD §10 — Local Backend).

Every handler is a thin translation over ``nexus_cli.core`` — no cluster
logic lives here that isn't already in ``core/``, so the CLI and the
dashboard can never silently disagree about what a given app's status means.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from dashboard.backend import prometheus
from dashboard.backend.auth import require_token
from nexus_cli.core import argocd, git, kubectl
from nexus_cli.core import chaos as core_chaos
from nexus_cli.core import dashboard as core_dashboard
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
    has_http_metrics: bool


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
    subject: str | None


class SyncLogResponse(BaseModel):
    app: str
    sync_status: str
    health_status: str
    last_sync_time: str | None
    history: list[SyncEventOut]


class MetricPoint(BaseModel):
    timestamp: float
    value: float


class MetricsResponse(BaseModel):
    cpu: list[MetricPoint]
    memory: list[MetricPoint]
    restarts: list[MetricPoint]
    desired_replicas: list[MetricPoint]
    available_replicas: list[MetricPoint]
    http_request_rate: list[MetricPoint]
    http_error_rate: list[MetricPoint]
    http_latency_p95: list[MetricPoint]


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
        try:
            has_http_metrics = kubectl.resource_exists(
                "servicemonitor", app.name, namespace=app.name
            )
        except NexusError:
            # Best-effort, like the replica lookup above — a hiccup here
            # shouldn't cost the user the whole Overview. Worst case, the App
            # Detail page just doesn't show the HTTP panels for this app.
            has_http_metrics = False
        summaries.append(
            AppSummary(
                name=app.name,
                sync_status=app.sync_status,
                health_status=app.health_status,
                last_sync_time=app.last_sync_time,
                desired_replicas=desired,
                available_replicas=available,
                has_http_metrics=has_http_metrics,
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
            name=p.name,
            phase=p.phase,
            restarts=p.restarts,
            problem=p.problem,
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


@router.get("/apps/{name}/metrics", response_model=MetricsResponse)
def app_metrics(name: str, window: str = prometheus.DEFAULT_WINDOW) -> MetricsResponse:
    """All native metrics-panel data for the App Detail view (PRD §10.2).

    Proxies Prometheus with the exact same PromQL the per-app Grafana
    dashboards already run (templates/grafana-dashboard.yaml.j2), so these
    panels and Grafana can never disagree. Every series is fetched here —
    including the HTTP ones, which return empty for an app that never
    opted into app.metricsPath — so the frontend needs exactly one poll per
    App Detail view instead of stitching this together with the Grafana
    reachability/embedding dance it used to do.
    """
    _app_or_404(name)
    try:
        window_seconds = prometheus.parse_window(window)
    except NexusError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    try:
        results = prometheus.query_range_many(
            {
                "cpu": prometheus.cpu_query(name),
                "memory": prometheus.memory_query(name),
                "restarts": prometheus.restarts_query(name),
                "desired_replicas": prometheus.desired_replicas_query(name),
                "available_replicas": prometheus.available_replicas_query(name),
                "http_request_rate": prometheus.http_request_rate_query(name),
                "http_error_rate": prometheus.http_error_rate_query(name),
                "http_latency_p95": prometheus.http_latency_p95_query(name),
            },
            window_seconds,
        )
    except NexusError as err:
        raise HTTPException(status_code=502, detail=str(err)) from err

    def points(pairs: list[tuple[float, float]]) -> list[MetricPoint]:
        return [MetricPoint(timestamp=ts, value=v) for ts, v in pairs]

    return MetricsResponse(
        cpu=points(results["cpu"]),
        memory=points(results["memory"]),
        restarts=points(results["restarts"]),
        desired_replicas=points(results["desired_replicas"]),
        available_replicas=points(results["available_replicas"]),
        http_request_rate=points(results["http_request_rate"]),
        http_error_rate=points(results["http_error_rate"]),
        http_latency_p95=points(results["http_latency_p95"]),
    )


def _commit_subject(revision: str | None) -> str | None:
    """Best-effort commit message lookup for one sync event.

    Only works when the SHA is fetched into the local checkout at
    ``NEXUS_APP_REPO_DIR`` (the directory ``nexus dashboard`` was launched
    from — see core/dashboard.py). For any *other* app's revisions, or if
    that repo doesn't have the commit, this returns None and the caller
    falls back to showing the bare SHA — the same thing this project always
    showed before this lookup existed, not a new failure mode.
    """
    if not revision:
        return None
    repo_dir = os.environ.get(core_dashboard.APP_REPO_DIR_ENV_VAR, ".")
    return git.commit_subject(revision, path=repo_dir)


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
        history=[
            SyncEventOut(
                revision=h.revision,
                deployed_at=h.deployed_at,
                subject=_commit_subject(h.revision),
            )
            for h in history
        ],
    )
