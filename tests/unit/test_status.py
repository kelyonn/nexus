"""Tests for the `nexus status` command (PRD §7.3)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from nexus_cli.commands import status as status_module
from nexus_cli.core import argocd, kubectl, preflight
from nexus_cli.core.output import NexusError
from nexus_cli.main import app

runner = CliRunner()

VALID_YAML = """
app:
  name: my-app
  image: myrepo/app:latest
  port: 8080
  healthPath: /health
platform:
  repoURL: https://github.com/user/repo.git
  branch: main
"""


def _write_config(tmp_path: Path) -> Path:
    p = tmp_path / "nexus.yaml"
    p.write_text(VALID_YAML)
    return p


def test_status_reports_preflight_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)

    def fail(**k: object) -> None:
        raise NexusError(what="cluster not reachable")

    monkeypatch.setattr(preflight, "ensure_cluster_ready", fail)
    result = runner.invoke(app, ["status"])
    assert result.exit_code != 0
    assert "cluster not reachable" in result.output


def test_status_missing_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(preflight, "ensure_cluster_ready", lambda **k: None)
    result = runner.invoke(app, ["status"])
    assert result.exit_code != 0


def test_status_missing_namespace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    monkeypatch.setattr(preflight, "ensure_cluster_ready", lambda **k: None)
    monkeypatch.setattr(kubectl, "namespace_exists", lambda ns: False)
    result = runner.invoke(app, ["status"])
    assert result.exit_code != 0
    assert "not found" in result.output


def test_status_happy_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    monkeypatch.setattr(preflight, "ensure_cluster_ready", lambda **k: None)
    monkeypatch.setattr(kubectl, "namespace_exists", lambda ns: True)
    monkeypatch.setattr(status_module, "replica_counts", lambda ns, name: (2, 2))
    monkeypatch.setattr(
        argocd,
        "get_status",
        lambda name: argocd.ArgoAppStatus(
            name=name,
            sync_status="Synced",
            health_status="Healthy",
            revision="abc",
            last_sync_time="2026-01-01",
        ),
    )
    monkeypatch.setattr(
        status_module,
        "list_pods",
        lambda ns: [
            status_module.PodInfo(name="my-app-abc123", phase="Running", restarts=0, problem=None)
        ],
    )
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0, result.output
    assert "2 / 2" in result.output
    assert "Synced" in result.output
    assert "Healthy" in result.output
    assert "my-app-abc123" in result.output


def test_status_not_registered_with_argocd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    monkeypatch.setattr(preflight, "ensure_cluster_ready", lambda **k: None)
    monkeypatch.setattr(kubectl, "namespace_exists", lambda ns: True)
    monkeypatch.setattr(status_module, "replica_counts", lambda ns, name: (2, 2))
    monkeypatch.setattr(argocd, "get_status", lambda name: None)
    monkeypatch.setattr(status_module, "list_pods", lambda ns: [])
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0, result.output
    assert "not registered" in result.output


def test_status_detects_image_pull_backoff(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    monkeypatch.setattr(preflight, "ensure_cluster_ready", lambda **k: None)
    monkeypatch.setattr(kubectl, "namespace_exists", lambda ns: True)
    monkeypatch.setattr(status_module, "replica_counts", lambda ns, name: (2, 0))
    monkeypatch.setattr(argocd, "get_status", lambda name: None)
    monkeypatch.setattr(
        status_module,
        "list_pods",
        lambda ns: [
            status_module.PodInfo(
                name="my-app-abc", phase="Pending", restarts=0, problem="ImagePullBackOff"
            )
        ],
    )
    monkeypatch.setattr(kubectl, "current_context", lambda: "minikube")
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0, result.output
    assert "ImagePullBackOff" in result.output
    assert "minikube image load" in result.output
    # default imagePullPolicy is Always — the fix must say the load alone
    # won't help, since the kubelet re-checks the registry regardless.
    assert "IfNotPresent" in result.output


def test_status_image_pull_backoff_fix_is_concise_when_already_if_not_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    p = tmp_path / "nexus.yaml"
    p.write_text(
        VALID_YAML.replace(
            "healthPath: /health", "healthPath: /health\n  imagePullPolicy: IfNotPresent"
        )
    )
    monkeypatch.setattr(preflight, "ensure_cluster_ready", lambda **k: None)
    monkeypatch.setattr(kubectl, "namespace_exists", lambda ns: True)
    monkeypatch.setattr(status_module, "replica_counts", lambda ns, name: (2, 0))
    monkeypatch.setattr(argocd, "get_status", lambda name: None)
    monkeypatch.setattr(
        status_module,
        "list_pods",
        lambda ns: [
            status_module.PodInfo(
                name="my-app-abc", phase="Pending", restarts=0, problem="ImagePullBackOff"
            )
        ],
    )
    monkeypatch.setattr(kubectl, "current_context", lambda: "minikube")
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0, result.output
    assert "minikube image load" in result.output
    assert "IfNotPresent" not in result.output  # already set — nothing to tell them to change


def test_status_detects_crash_loop_backoff(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    monkeypatch.setattr(preflight, "ensure_cluster_ready", lambda **k: None)
    monkeypatch.setattr(kubectl, "namespace_exists", lambda ns: True)
    monkeypatch.setattr(status_module, "replica_counts", lambda ns, name: (2, 1))
    monkeypatch.setattr(argocd, "get_status", lambda name: None)
    monkeypatch.setattr(
        status_module,
        "list_pods",
        lambda ns: [
            status_module.PodInfo(
                name="my-app-xyz", phase="Running", restarts=5, problem="CrashLoopBackOff"
            )
        ],
    )
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0, result.output
    assert "CrashLoopBackOff" in result.output
    assert "kubectl -n my-app logs" in result.output


def test_status_no_pods(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    monkeypatch.setattr(preflight, "ensure_cluster_ready", lambda **k: None)
    monkeypatch.setattr(kubectl, "namespace_exists", lambda ns: True)
    monkeypatch.setattr(status_module, "replica_counts", lambda ns, name: (0, 0))
    monkeypatch.setattr(argocd, "get_status", lambda name: None)
    monkeypatch.setattr(status_module, "list_pods", lambda ns: [])
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0, result.output
    assert "(none)" in result.output


def test_image_pull_fix_non_minikube(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(kubectl, "current_context", lambda: "eks-prod")
    fix = status_module.image_pull_fix()
    assert "registry" in fix.lower()


def test_image_pull_fix_minikube(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(kubectl, "current_context", lambda: "minikube")
    fix = status_module.image_pull_fix()
    assert "minikube image load" in fix
