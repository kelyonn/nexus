"""Unit tests for nexus_cli.core.argocd (mocked kubectl; no live cluster)."""

from __future__ import annotations

import pytest

from nexus_cli.core import argocd
from nexus_cli.core.output import NexusError


def test_register_applies_manifest(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}
    monkeypatch.setattr(
        argocd.kubectl, "apply_manifest", lambda text: captured.setdefault("text", text)
    )
    argocd.register("kind: Application")
    assert captured["text"] == "kind: Application"


def test_get_status_parses_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    doc = {
        "status": {
            "sync": {"status": "Synced", "revision": "abc123"},
            "health": {"status": "Healthy"},
            "operationState": {"finishedAt": "2026-01-01T00:00:00Z"},
        }
    }
    monkeypatch.setattr(argocd.kubectl, "get_json", lambda *a, **k: doc)
    result = argocd.get_status("my-app")
    assert result is not None
    assert result.sync_status == "Synced"
    assert result.health_status == "Healthy"
    assert result.revision == "abc123"
    assert result.last_sync_time == "2026-01-01T00:00:00Z"


def test_get_status_returns_none_when_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_not_found(*a: object, **k: object) -> None:
        raise NexusError(what="not found")

    monkeypatch.setattr(argocd.kubectl, "get_json", raise_not_found)
    assert argocd.get_status("missing-app") is None


def test_get_status_defaults_to_unknown_for_missing_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(argocd.kubectl, "get_json", lambda *a, **k: {})
    result = argocd.get_status("my-app")
    assert result is not None
    assert result.sync_status == "Unknown"
    assert result.health_status == "Unknown"


def _app_item(name: str, *, managed: bool = True, sync: str = "Synced") -> dict:
    labels = {"managed-by": "nexus"} if managed else {"managed-by": "someone-else"}
    return {
        "metadata": {"name": name, "labels": labels},
        "status": {"sync": {"status": sync}, "health": {"status": "Healthy"}},
    }


def test_list_managed_apps_filters_by_label_and_sorts(monkeypatch: pytest.MonkeyPatch) -> None:
    doc = {
        "items": [
            _app_item("zebra-app"),
            _app_item("not-ours", managed=False),
            _app_item("alpha-app"),
        ]
    }
    monkeypatch.setattr(argocd.kubectl, "get_json", lambda *a, **k: doc)
    apps = argocd.list_managed_apps()
    assert [a.name for a in apps] == ["alpha-app", "zebra-app"]
    assert apps[0].sync_status == "Synced"
    assert apps[0].health_status == "Healthy"


def test_list_managed_apps_skips_items_without_labels(monkeypatch: pytest.MonkeyPatch) -> None:
    doc = {"items": [{"metadata": {"name": "bare-app"}}, _app_item("ours")]}
    monkeypatch.setattr(argocd.kubectl, "get_json", lambda *a, **k: doc)
    assert [a.name for a in argocd.list_managed_apps()] == ["ours"]


def test_list_managed_apps_empty_when_argocd_crd_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """No ArgoCD on the cluster is a legitimate 'no Nexus apps', not an error."""

    def raise_no_crd(*a: object, **k: object) -> None:
        raise NexusError(
            what="kubectl get application failed.",
            why='error: the server doesn\'t have a resource type "application"',
        )

    monkeypatch.setattr(argocd.kubectl, "get_json", raise_no_crd)
    assert argocd.list_managed_apps() == []


def test_list_managed_apps_reraises_real_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unreachable cluster must not be reported as 'no apps'."""

    def raise_unreachable(*a: object, **k: object) -> None:
        raise NexusError(
            what="kubectl get application failed.",
            why="Unable to connect to the server: dial tcp: i/o timeout",
        )

    monkeypatch.setattr(argocd.kubectl, "get_json", raise_unreachable)
    with pytest.raises(NexusError, match="Unable to connect"):
        argocd.list_managed_apps()


def test_sync_history_sorts_most_recent_first(monkeypatch: pytest.MonkeyPatch) -> None:
    doc = {
        "status": {
            "history": [
                {"revision": "abc123", "deployedAt": "2026-01-01T00:00:00Z"},
                {"revision": "def456", "deployedAt": "2026-01-02T00:00:00Z"},
            ]
        }
    }
    monkeypatch.setattr(argocd.kubectl, "get_json", lambda *a, **k: doc)
    events = argocd.sync_history("my-app")
    assert [e.revision for e in events] == ["def456", "abc123"]


def test_sync_history_handles_entries_missing_deployed_at(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sorting keys off `deployed_at or ""`, so null/absent timestamps must not
    blow up on a str/None comparison — they sort last.
    """
    doc = {
        "status": {
            "history": [
                {"revision": "no-timestamp"},
                {"revision": "newer", "deployedAt": "2026-01-02T00:00:00Z"},
                {"revision": "null-timestamp", "deployedAt": None},
                {"revision": "older", "deployedAt": "2026-01-01T00:00:00Z"},
            ]
        }
    }
    monkeypatch.setattr(argocd.kubectl, "get_json", lambda *a, **k: doc)
    events = argocd.sync_history("my-app")
    assert [e.revision for e in events[:2]] == ["newer", "older"]
    assert {e.revision for e in events[2:]} == {"no-timestamp", "null-timestamp"}
    assert all(e.deployed_at is None for e in events[2:])


def test_sync_history_empty_when_no_history_yet(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(argocd.kubectl, "get_json", lambda *a, **k: {"status": {}})
    assert argocd.sync_history("my-app") == []


def test_sync_history_empty_when_app_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_not_found(*a: object, **k: object) -> None:
        raise NexusError(what="not found")

    monkeypatch.setattr(argocd.kubectl, "get_json", raise_not_found)
    assert argocd.sync_history("missing-app") == []


def test_trigger_sync_patches_refresh_annotation(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, list[str]] = {}
    monkeypatch.setattr(argocd.kubectl, "run", lambda args, **k: captured.setdefault("args", args))
    argocd.trigger_sync("my-app")
    assert "patch" in captured["args"]
    assert "refresh" in captured["args"][-1]


def test_wait_for_healthy_returns_when_synced_and_healthy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        argocd,
        "get_status",
        lambda name: argocd.ArgoAppStatus(
            name=name,
            sync_status="Synced",
            health_status="Healthy",
            revision="x",
            last_sync_time="t",
        ),
    )
    result = argocd.wait_for_healthy("my-app", timeout=5, poll_interval=0)
    assert result.sync_status == "Synced"


def _progressing_status(name: str) -> argocd.ArgoAppStatus:
    return argocd.ArgoAppStatus(
        name=name,
        sync_status="Synced",
        health_status="Progressing",
        revision="x",
        last_sync_time="t",
    )


def test_wait_for_healthy_accepts_progressing_when_deployment_actually_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ArgoCD v3.4.5 quirk: health stuck on Progressing for a Deployment
    Kubernetes itself reports fully available. Ground truth wins.
    """
    monkeypatch.setattr(argocd, "get_status", _progressing_status)
    monkeypatch.setattr(argocd.status, "replica_counts", lambda ns, name: (2, 2))

    result = argocd.wait_for_healthy("my-app", timeout=5, poll_interval=0)

    assert result.sync_status == "Synced"
    assert result.health_status == "Progressing"  # unmodified — real ArgoCD truth


def test_wait_for_healthy_still_times_out_when_progressing_and_not_actually_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Progressing alone is never enough — only overridden when the Deployment
    itself confirms every replica is up.
    """
    monkeypatch.setattr(argocd, "get_status", _progressing_status)
    monkeypatch.setattr(argocd.status, "replica_counts", lambda ns, name: (2, 1))
    fake_clock = iter([0, 1, 2, 100])
    monkeypatch.setattr(argocd.time, "monotonic", lambda: next(fake_clock))
    monkeypatch.setattr(argocd.time, "sleep", lambda s: None)

    with pytest.raises(NexusError, match="did not become Synced"):
        argocd.wait_for_healthy("my-app", timeout=5, poll_interval=0)


def test_wait_for_healthy_does_not_override_degraded(monkeypatch: pytest.MonkeyPatch) -> None:
    """Degraded/Missing are real problems ArgoCD is reporting — never overridden,
    even if the ground-truth check would otherwise pass.
    """
    monkeypatch.setattr(
        argocd,
        "get_status",
        lambda name: argocd.ArgoAppStatus(
            name=name,
            sync_status="Synced",
            health_status="Degraded",
            revision="x",
            last_sync_time="t",
        ),
    )
    monkeypatch.setattr(argocd.status, "replica_counts", lambda ns, name: (2, 2))
    fake_clock = iter([0, 1, 2, 100])
    monkeypatch.setattr(argocd.time, "monotonic", lambda: next(fake_clock))
    monkeypatch.setattr(argocd.time, "sleep", lambda s: None)

    with pytest.raises(NexusError, match="did not become Synced"):
        argocd.wait_for_healthy("my-app", timeout=5, poll_interval=0)


def test_deployment_actually_ready_false_on_kubectl_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A kubectl failure while cross-checking must never masquerade as 'ready'."""

    def raise_err(namespace: str, name: str) -> tuple[int, int]:
        raise NexusError(what="deployment not found")

    monkeypatch.setattr(argocd.status, "replica_counts", raise_err)
    assert argocd._deployment_actually_ready("my-app") is False


def test_wait_for_healthy_raises_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        argocd,
        "get_status",
        lambda name: argocd.ArgoAppStatus(
            name=name,
            sync_status="OutOfSync",
            health_status="Degraded",
            revision=None,
            last_sync_time=None,
        ),
    )
    fake_clock = iter([0, 1, 2, 100])
    monkeypatch.setattr(argocd.time, "monotonic", lambda: next(fake_clock))
    monkeypatch.setattr(argocd.time, "sleep", lambda s: None)
    with pytest.raises(NexusError) as exc_info:
        argocd.wait_for_healthy("my-app", timeout=5, poll_interval=0)
    assert "did not become Synced" in exc_info.value.what
