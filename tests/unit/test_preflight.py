"""Unit tests for nexus_cli.core.preflight (mocked kubectl/helm)."""

from __future__ import annotations

import pytest

from nexus_cli.core import preflight
from nexus_cli.core.output import NexusError


def _ok(name: str) -> preflight.PreflightCheck:
    return preflight.PreflightCheck(name, True, "ok")


def test_check_kubectl_installed_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(preflight.kubectl, "version_client", lambda: "v1.29.0")
    check = preflight.check_kubectl_installed()
    assert check.passed is True
    assert "v1.29.0" in check.detail


def test_check_kubectl_installed_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(preflight.kubectl, "version_client", lambda: None)
    check = preflight.check_kubectl_installed()
    assert check.passed is False


def test_check_helm_installed_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(preflight.helm, "version", lambda: "v3.14.1")
    check = preflight.check_helm_installed()
    assert check.passed is True


def test_check_helm_installed_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(preflight.helm, "version", lambda: None)
    check = preflight.check_helm_installed()
    assert check.passed is False


def test_check_cluster_reachable_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(preflight.kubectl, "current_context", lambda: "minikube")
    monkeypatch.setattr(preflight.kubectl, "cluster_reachable", lambda: True)
    check = preflight.check_cluster_reachable()
    assert check.passed is True
    assert "minikube" in check.detail


def test_check_cluster_reachable_fail_no_context(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(preflight.kubectl, "current_context", lambda: None)
    monkeypatch.setattr(preflight.kubectl, "cluster_reachable", lambda: False)
    check = preflight.check_cluster_reachable()
    assert check.passed is False


def test_run_includes_helm_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(preflight, "check_kubectl_installed", lambda: _ok("kubectl"))
    monkeypatch.setattr(preflight, "check_helm_installed", lambda: _ok("helm"))
    monkeypatch.setattr(preflight, "check_cluster_reachable", lambda: _ok("cluster"))
    checks = preflight.run()
    assert [c.name for c in checks] == ["kubectl", "helm", "cluster"]


def test_run_excludes_helm_when_not_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(preflight, "check_kubectl_installed", lambda: _ok("kubectl"))
    monkeypatch.setattr(preflight, "check_cluster_reachable", lambda: _ok("cluster"))
    checks = preflight.run(require_helm=False)
    assert [c.name for c in checks] == ["kubectl", "cluster"]


def test_ensure_cluster_ready_passes_when_all_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        preflight,
        "run",
        lambda **kw: [
            preflight.PreflightCheck("kubectl", True, "ok"),
            preflight.PreflightCheck("cluster", True, "ok"),
        ],
    )
    preflight.ensure_cluster_ready()  # should not raise


def test_ensure_cluster_ready_raises_on_first_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        preflight,
        "run",
        lambda **kw: [
            preflight.PreflightCheck("kubectl", False, "kubectl not found"),
            preflight.PreflightCheck("cluster", True, "ok"),
        ],
    )
    with pytest.raises(NexusError) as exc_info:
        preflight.ensure_cluster_ready()
    assert "kubectl" in exc_info.value.what
