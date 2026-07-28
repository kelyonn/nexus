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
from dashboard.backend.routes import core_chaos, core_status  # noqa: E402
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
        }
    ]


def test_list_apps_defaults_replicas_to_zero_when_deployment_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A registered-but-not-yet-synced app is still a real app to show, not an error."""
    monkeypatch.setattr(argocd, "list_managed_apps", lambda: [_app_status("my-app")])

    def raise_not_found(namespace: str, name: str) -> tuple[int, int]:
        raise NexusError(what="deployment not found")

    monkeypatch.setattr(core_status, "replica_counts", raise_not_found)

    resp = client.get("/api/apps")
    assert resp.status_code == 200
    assert resp.json()[0]["desired_replicas"] == 0
    assert resp.json()[0]["available_replicas"] == 0


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
            core_status.PodInfo(name="my-app-abc", phase="Running", restarts=0, problem=None)
        ],
    )
    resp = client.get("/api/apps/my-app/pods")
    assert resp.status_code == 200
    assert resp.json() == [
        {"name": "my-app-abc", "phase": "Running", "restarts": 0, "problem": None}
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
