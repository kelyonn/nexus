"""Unit tests for nexus_cli.core.status (mocked kubectl; no live cluster).

`commands/test_status.py` mocks these functions out entirely to test the CLI
narration; this file exercises the real bodies, which nothing else did once
they moved out of `commands/status.py` (formerly untracked by the core/
coverage gate, since commands/ isn't part of it).
"""

from __future__ import annotations

import pytest

from nexus_cli.core import status


def _pod(
    name: str,
    *,
    phase: str = "Running",
    container_statuses: list[dict] | None = None,
    created_at: str | None = None,
) -> dict:
    metadata = {"name": name}
    if created_at is not None:
        metadata["creationTimestamp"] = created_at
    return {
        "metadata": metadata,
        "status": {
            "phase": phase,
            "containerStatuses": container_statuses or [],
        },
    }


def test_list_pods_parses_phase_and_restarts(monkeypatch: pytest.MonkeyPatch) -> None:
    doc = {
        "items": [
            _pod(
                "my-app-abc",
                container_statuses=[{"restartCount": 2}, {"restartCount": 1}],
            )
        ]
    }
    monkeypatch.setattr(status.kubectl, "get_json", lambda *a, **k: doc)
    pods = status.list_pods("my-app")
    assert pods == [status.PodInfo(name="my-app-abc", phase="Running", restarts=3, problem=None)]


def test_list_pods_empty_namespace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(status.kubectl, "get_json", lambda *a, **k: {"items": []})
    assert status.list_pods("my-app") == []


def test_list_pods_detects_image_pull_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    doc = {
        "items": [
            _pod(
                "my-app-abc",
                phase="Pending",
                container_statuses=[
                    {"restartCount": 0, "state": {"waiting": {"reason": "ImagePullBackOff"}}}
                ],
            )
        ]
    }
    monkeypatch.setattr(status.kubectl, "get_json", lambda *a, **k: doc)
    pods = status.list_pods("my-app")
    assert pods[0].problem == "ImagePullBackOff"


def test_list_pods_detects_crash_loop_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    doc = {
        "items": [
            _pod(
                "my-app-abc",
                container_statuses=[
                    {"restartCount": 5, "state": {"waiting": {"reason": "CrashLoopBackOff"}}}
                ],
            )
        ]
    }
    monkeypatch.setattr(status.kubectl, "get_json", lambda *a, **k: doc)
    pods = status.list_pods("my-app")
    assert pods[0].problem == "CrashLoopBackOff"
    assert pods[0].restarts == 5


def test_list_pods_ignores_other_waiting_reasons(monkeypatch: pytest.MonkeyPatch) -> None:
    doc = {
        "items": [
            _pod(
                "my-app-abc",
                phase="Pending",
                container_statuses=[
                    {"restartCount": 0, "state": {"waiting": {"reason": "ContainerCreating"}}}
                ],
            )
        ]
    }
    monkeypatch.setattr(status.kubectl, "get_json", lambda *a, **k: doc)
    assert status.list_pods("my-app")[0].problem is None


def test_list_pods_defaults_phase_to_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    doc = {"items": [{"metadata": {"name": "my-app-abc"}, "status": {}}]}
    monkeypatch.setattr(status.kubectl, "get_json", lambda *a, **k: doc)
    assert status.list_pods("my-app")[0].phase == "Unknown"


def test_list_pods_includes_creation_timestamp(monkeypatch: pytest.MonkeyPatch) -> None:
    doc = {"items": [_pod("my-app-abc", created_at="2026-01-01T00:00:00Z")]}
    monkeypatch.setattr(status.kubectl, "get_json", lambda *a, **k: doc)
    assert status.list_pods("my-app")[0].created_at == "2026-01-01T00:00:00Z"


def test_list_pods_created_at_none_when_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    doc = {"items": [_pod("my-app-abc")]}
    monkeypatch.setattr(status.kubectl, "get_json", lambda *a, **k: doc)
    assert status.list_pods("my-app")[0].created_at is None


def test_replica_counts_reads_spec_and_status(monkeypatch: pytest.MonkeyPatch) -> None:
    doc = {"spec": {"replicas": 3}, "status": {"availableReplicas": 2}}
    monkeypatch.setattr(status.kubectl, "get_json", lambda *a, **k: doc)
    assert status.replica_counts("my-app", "my-app") == (3, 2)


def test_replica_counts_defaults_to_zero_when_fields_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(status.kubectl, "get_json", lambda *a, **k: {})
    assert status.replica_counts("my-app", "my-app") == (0, 0)


def test_rollout_complete_true_when_available_and_updated_meet_desired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    doc = {"spec": {"replicas": 2}, "status": {"availableReplicas": 2, "updatedReplicas": 2}}
    monkeypatch.setattr(status.kubectl, "get_json", lambda *a, **k: doc)
    assert status.rollout_complete("my-app", "my-app") is True


def test_rollout_complete_false_when_old_replicas_satisfy_available_but_not_updated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale ReplicaSet's still-healthy pods can satisfy ``availableReplicas``
    on their own while a new bad pod means the rollout hasn't completed —
    ``updatedReplicas`` must also meet the desired count.
    """
    doc = {"spec": {"replicas": 2}, "status": {"availableReplicas": 2, "updatedReplicas": 1}}
    monkeypatch.setattr(status.kubectl, "get_json", lambda *a, **k: doc)
    assert status.rollout_complete("my-app", "my-app") is False


def test_rollout_complete_false_when_desired_is_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    doc = {"spec": {"replicas": 0}, "status": {}}
    monkeypatch.setattr(status.kubectl, "get_json", lambda *a, **k: doc)
    assert status.rollout_complete("my-app", "my-app") is False


def test_image_pull_fix_minikube(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(status.kubectl, "current_context", lambda: "minikube")
    assert "minikube image load" in status.image_pull_fix()


def test_image_pull_fix_minikube_always_policy_warns_load_wont_help_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Under the default `Always`, the kubelet re-checks the registry
    regardless of what's locally loaded — the fix must say so, not just
    suggest a load that silently won't work.
    """
    monkeypatch.setattr(status.kubectl, "current_context", lambda: "minikube")
    fix = status.image_pull_fix("Always")
    assert "minikube image load" in fix
    assert "IfNotPresent" in fix


def test_image_pull_fix_minikube_if_not_present_policy_load_alone_suffices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(status.kubectl, "current_context", lambda: "minikube")
    fix = status.image_pull_fix("IfNotPresent")
    assert "minikube image load" in fix
    assert "IfNotPresent" not in fix  # already set — no need to tell the user to change it


def test_image_pull_fix_other_context(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(status.kubectl, "current_context", lambda: "eks-prod")
    assert "registry" in status.image_pull_fix().lower()


def test_image_pull_fix_no_context(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(status.kubectl, "current_context", lambda: None)
    assert "registry" in status.image_pull_fix().lower()
