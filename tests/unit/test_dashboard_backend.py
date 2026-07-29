"""Unit tests for the dashboard FastAPI backend (mocked core/*; no live cluster).

Requires the `dashboard` extra (fastapi + the TestClient's http client) —
skipped entirely if it isn't installed, so `pytest -q` still works for a dev
who only did `pip install -e ".[dev]"`.
"""

from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from dashboard.backend import auth as auth_module  # noqa: E402
from dashboard.backend.main import app  # noqa: E402
from dashboard.backend.routes import (  # noqa: E402
    core_chaos,
    core_dashboard,
    core_status,
    git,
    kubectl,
    prometheus,
)
from nexus_cli.core import argocd  # noqa: E402
from nexus_cli.core.output import NexusError  # noqa: E402

client = TestClient(app)


def _app_status(
    name: str, *, sync: str = "Synced", health: str = "Healthy"
) -> argocd.ArgoAppStatus:
    return argocd.ArgoAppStatus(
        name=name, sync_status=sync, health_status=health, revision="abc123", last_sync_time="t"
    )


def test_health_endpoint() -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_cors_restricted_to_frontend_origin() -> None:
    resp = client.options(
        "/api/apps",
        headers={
            "Origin": "http://localhost:3001",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.headers["access-control-allow-origin"] == "http://localhost:3001"


# --- GET /api/apps ---


def test_list_apps_returns_summaries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(argocd, "list_managed_apps", lambda: [_app_status("my-app")])
    monkeypatch.setattr(core_status, "replica_counts", lambda ns, name: (2, 2))
    monkeypatch.setattr(kubectl, "resource_exists", lambda resource, name, namespace: True)

    resp = client.get("/api/apps")
    assert resp.status_code == 200
    body = resp.json()
    assert body == [
        {
            "name": "my-app",
            "sync_status": "Synced",
            "health_status": "Healthy",
            "last_sync_time": "t",
            "desired_replicas": 2,
            "available_replicas": 2,
            "has_http_metrics": True,
        }
    ]


def test_list_apps_has_http_metrics_false_when_no_servicemonitor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(argocd, "list_managed_apps", lambda: [_app_status("my-app")])
    monkeypatch.setattr(core_status, "replica_counts", lambda ns, name: (2, 2))
    monkeypatch.setattr(kubectl, "resource_exists", lambda resource, name, namespace: False)

    resp = client.get("/api/apps")
    assert resp.status_code == 200
    assert resp.json()[0]["has_http_metrics"] is False


def test_list_apps_defaults_replicas_to_zero_when_deployment_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A registered-but-not-yet-synced app is still a real app to show, not an error."""
    monkeypatch.setattr(argocd, "list_managed_apps", lambda: [_app_status("my-app")])

    def raise_not_found(namespace: str, name: str) -> tuple[int, int]:
        raise NexusError(
            what="kubectl get deployment failed.",
            why='Error from server (NotFound): deployments.apps "my-app" not found',
        )

    monkeypatch.setattr(core_status, "replica_counts", raise_not_found)
    monkeypatch.setattr(kubectl, "resource_exists", lambda resource, name, namespace: False)

    resp = client.get("/api/apps")
    assert resp.status_code == 200
    assert resp.json()[0]["desired_replicas"] == 0
    assert resp.json()[0]["available_replicas"] == 0


def test_list_apps_does_not_disguise_rbac_failure_as_zero_replicas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """"0 replicas" looks identical to a scaled-down app — a permissions
    failure must surface as an error instead of that lie.
    """
    monkeypatch.setattr(argocd, "list_managed_apps", lambda: [_app_status("my-app")])

    def raise_forbidden(namespace: str, name: str) -> tuple[int, int]:
        raise NexusError(
            what="kubectl get deployment failed.",
            why="deployments.apps is forbidden: User cannot get resource",
        )

    monkeypatch.setattr(core_status, "replica_counts", raise_forbidden)

    resp = client.get("/api/apps")
    assert resp.status_code == 502
    assert "forbidden" in resp.json()["detail"]


def test_list_apps_surfaces_cluster_failure_as_502(monkeypatch: pytest.MonkeyPatch) -> None:
    """A real failure (cluster unreachable) must not become a bare 500 with no message."""

    def raise_unreachable() -> list[argocd.ArgoAppStatus]:
        raise NexusError(what="kubectl get application failed.", why="connection refused")

    monkeypatch.setattr(argocd, "list_managed_apps", raise_unreachable)
    resp = client.get("/api/apps")
    assert resp.status_code == 502
    assert "connection refused" in resp.json()["detail"]


def test_list_apps_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(argocd, "list_managed_apps", lambda: [])
    resp = client.get("/api/apps")
    assert resp.status_code == 200
    assert resp.json() == []


# --- GET /api/apps/{name}/pods ---


def test_list_pods_returns_404_for_unknown_app(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(argocd, "get_status", lambda name: None)
    resp = client.get("/api/apps/ghost-app/pods")
    assert resp.status_code == 404


def test_list_pods_returns_pod_data(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(argocd, "get_status", lambda name: _app_status(name))
    monkeypatch.setattr(
        core_status,
        "list_pods",
        lambda ns: [
            core_status.PodInfo(
                name="my-app-abc",
                phase="Running",
                restarts=0,
                problem=None,
                created_at="2026-01-01T00:00:00Z",
            )
        ],
    )
    resp = client.get("/api/apps/my-app/pods")
    assert resp.status_code == 200
    assert resp.json() == [
        {
            "name": "my-app-abc",
            "phase": "Running",
            "restarts": 0,
            "problem": None,
            "created_at": "2026-01-01T00:00:00Z",
        }
    ]


def test_list_pods_surfaces_kubectl_failure_as_502(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(argocd, "get_status", lambda name: _app_status(name))

    def raise_err(namespace: str) -> list[core_status.PodInfo]:
        raise NexusError(what="cluster unreachable")

    monkeypatch.setattr(core_status, "list_pods", raise_err)
    resp = client.get("/api/apps/my-app/pods")
    assert resp.status_code == 502


# --- POST /api/apps/{name}/chaos (token-gated) ---


def test_chaos_without_token_configured_returns_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(auth_module.TOKEN_ENV_VAR, raising=False)
    resp = client.post("/api/apps/my-app/chaos", json={})
    assert resp.status_code == 503


def test_chaos_with_wrong_token_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(auth_module.TOKEN_ENV_VAR, "correct-token")
    resp = client.post(
        "/api/apps/my-app/chaos",
        json={},
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert resp.status_code == 401


def test_chaos_with_missing_header_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(auth_module.TOKEN_ENV_VAR, "correct-token")
    resp = client.post("/api/apps/my-app/chaos", json={})
    assert resp.status_code == 401


def test_chaos_with_correct_token_triggers_experiment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(auth_module.TOKEN_ENV_VAR, "correct-token")
    monkeypatch.setattr(argocd, "get_status", lambda name: _app_status(name))
    monkeypatch.setattr(
        core_chaos,
        "run_experiment",
        lambda app_name, *, action, kill_all: f"{app_name}-chaos-abc123",
    )

    resp = client.post(
        "/api/apps/my-app/chaos",
        json={"action": "pod-kill", "kill_all": False},
        headers={"Authorization": "Bearer correct-token"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"run_name": "my-app-chaos-abc123"}


def test_chaos_returns_404_for_unknown_app_even_with_valid_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(auth_module.TOKEN_ENV_VAR, "correct-token")
    monkeypatch.setattr(argocd, "get_status", lambda name: None)
    resp = client.post(
        "/api/apps/ghost-app/chaos",
        json={},
        headers={"Authorization": "Bearer correct-token"},
    )
    assert resp.status_code == 404


def test_chaos_invalid_action_returns_400(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(auth_module.TOKEN_ENV_VAR, "correct-token")
    monkeypatch.setattr(argocd, "get_status", lambda name: _app_status(name))

    def raise_invalid(app_name: str, *, action: str, kill_all: bool) -> str:
        raise NexusError(what=f"Unknown chaos action '{action}'.")

    monkeypatch.setattr(core_chaos, "run_experiment", raise_invalid)

    resp = client.post(
        "/api/apps/my-app/chaos",
        json={"action": "nope"},
        headers={"Authorization": "Bearer correct-token"},
    )
    assert resp.status_code == 400


# --- GET /api/apps/{name}/synclog ---


def test_synclog_returns_404_for_unknown_app(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(argocd, "get_status", lambda name: None)
    resp = client.get("/api/apps/ghost-app/synclog")
    assert resp.status_code == 404


def test_synclog_returns_current_status_and_history(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(argocd, "get_status", lambda name: _app_status(name))
    monkeypatch.setattr(
        argocd,
        "sync_history",
        lambda name: [
            argocd.SyncEvent(revision="def456", deployed_at="2026-01-02T00:00:00Z"),
            argocd.SyncEvent(revision="abc123", deployed_at="2026-01-01T00:00:00Z"),
        ],
    )
    monkeypatch.setattr(git, "commit_subject", lambda sha, path=".": None)
    resp = client.get("/api/apps/my-app/synclog")
    assert resp.status_code == 200
    body = resp.json()
    assert body["app"] == "my-app"
    assert body["sync_status"] == "Synced"
    assert len(body["history"]) == 2
    assert body["history"][0]["revision"] == "def456"


def test_synclog_empty_history_for_never_synced_app(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(argocd, "get_status", lambda name: _app_status(name))
    monkeypatch.setattr(argocd, "sync_history", lambda name: [])
    resp = client.get("/api/apps/my-app/synclog")
    assert resp.status_code == 200
    assert resp.json()["history"] == []


def test_synclog_includes_commit_subject_when_available_locally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(argocd, "get_status", lambda name: _app_status(name))
    monkeypatch.setattr(
        argocd,
        "sync_history",
        lambda name: [argocd.SyncEvent(revision="abc123", deployed_at="2026-01-01T00:00:00Z")],
    )
    monkeypatch.setattr(
        git,
        "commit_subject",
        lambda sha, path=".": "nexus: upgrade image to v2" if sha == "abc123" else None,
    )
    resp = client.get("/api/apps/my-app/synclog")
    assert resp.status_code == 200
    assert resp.json()["history"][0]["subject"] == "nexus: upgrade image to v2"


def test_synclog_subject_none_when_commit_not_found_locally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A revision from an app deployed by someone else, or a different repo
    entirely, is an ordinary case — falls back to no subject, not an error.
    """
    monkeypatch.setattr(argocd, "get_status", lambda name: _app_status(name))
    monkeypatch.setattr(
        argocd,
        "sync_history",
        lambda name: [argocd.SyncEvent(revision="unknown-sha", deployed_at="2026-01-01T00:00:00Z")],
    )
    monkeypatch.setattr(git, "commit_subject", lambda sha, path=".": None)
    resp = client.get("/api/apps/my-app/synclog")
    assert resp.status_code == 200
    assert resp.json()["history"][0]["subject"] is None


def test_synclog_uses_app_repo_dir_env_var_for_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(argocd, "get_status", lambda name: _app_status(name))
    monkeypatch.setattr(
        argocd,
        "sync_history",
        lambda name: [argocd.SyncEvent(revision="abc123", deployed_at="t")],
    )
    monkeypatch.setenv(core_dashboard.APP_REPO_DIR_ENV_VAR, "/some/app/checkout")
    captured: dict[str, str] = {}

    def fake_commit_subject(sha: str, path: str = ".") -> str | None:
        captured["path"] = path
        return None

    monkeypatch.setattr(git, "commit_subject", fake_commit_subject)
    client.get("/api/apps/my-app/synclog")
    assert captured["path"] == "/some/app/checkout"


# --- GET /api/apps/{name}/metrics ---


def test_metrics_returns_404_for_unknown_app(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(argocd, "get_status", lambda name: None)
    resp = client.get("/api/apps/ghost-app/metrics")
    assert resp.status_code == 404


def test_metrics_returns_cpu_and_memory_series(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(argocd, "get_status", lambda name: _app_status(name))

    def fake_query_range(promql: str, window_seconds: int) -> list[tuple[float, float]]:
        if "cpu" in promql:
            return [(1000.0, 0.1), (1015.0, 0.2)]
        return [(1000.0, 1048576.0)]

    monkeypatch.setattr(prometheus, "query_range", fake_query_range)
    resp = client.get("/api/apps/my-app/metrics")
    assert resp.status_code == 200
    body = resp.json()
    assert body["cpu"] == [
        {"timestamp": 1000.0, "value": 0.1},
        {"timestamp": 1015.0, "value": 0.2},
    ]
    assert body["memory"] == [{"timestamp": 1000.0, "value": 1048576.0}]


def test_metrics_bad_window_returns_400(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(argocd, "get_status", lambda name: _app_status(name))
    resp = client.get("/api/apps/my-app/metrics", params={"window": "nonsense"})
    assert resp.status_code == 400
    assert "Unsupported metrics window" in resp.json()["detail"]


def test_metrics_prometheus_unreachable_returns_502(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(argocd, "get_status", lambda name: _app_status(name))

    def raise_unreachable(promql: str, window_seconds: int) -> list[tuple[float, float]]:
        raise NexusError(what="Could not reach Prometheus.", why="Connection refused")

    monkeypatch.setattr(prometheus, "query_range", raise_unreachable)
    resp = client.get("/api/apps/my-app/metrics")
    assert resp.status_code == 502
    assert "Could not reach Prometheus" in resp.json()["detail"]


def test_metrics_empty_when_app_has_no_series_yet(monkeypatch: pytest.MonkeyPatch) -> None:
    """A freshly deployed app with no traffic yet is empty data, not an error."""
    monkeypatch.setattr(argocd, "get_status", lambda name: _app_status(name))
    monkeypatch.setattr(prometheus, "query_range", lambda promql, window_seconds: [])
    resp = client.get("/api/apps/my-app/metrics")
    assert resp.status_code == 200
    assert resp.json() == {"cpu": [], "memory": []}
