"""Tests for the `nexus destroy` command (PRD §7.5, §8)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from nexus_cli.commands import destroy as destroy_module
from nexus_cli.core import kubectl, preflight
from nexus_cli.core.config import AppConfig, NexusConfig, PlatformConfig
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


def _minimal_config(*, monitoring: bool = True, chaos: bool = False) -> NexusConfig:
    return NexusConfig(
        app=AppConfig(name="my-app", image="repo/app:latest", port=8080, healthPath="/health"),
        platform=PlatformConfig(
            repoURL="https://github.com/user/repo.git",
            branch="main",
            monitoring=monitoring,
            chaos=chaos,
        ),
    )


def test_destroy_preflight_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)

    def fail(**k: object) -> None:
        raise NexusError(what="cluster not reachable")

    monkeypatch.setattr(preflight, "ensure_cluster_ready", fail)
    result = runner.invoke(app, ["destroy"])
    assert result.exit_code != 0
    assert "cluster not reachable" in result.output


def test_destroy_aborts_on_name_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    monkeypatch.setattr(preflight, "ensure_cluster_ready", lambda **k: None)

    result = runner.invoke(app, ["destroy"], input="wrong-name\n")
    assert result.exit_code != 0
    assert "did not match" in result.output


def test_destroy_happy_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    monkeypatch.setattr(preflight, "ensure_cluster_ready", lambda **k: None)
    monkeypatch.setattr(kubectl, "delete", lambda *a, **k: None)

    result = runner.invoke(app, ["destroy"], input="my-app\n")
    assert result.exit_code == 0, result.output
    assert "will be permanently deleted" in result.output
    assert "ArgoCD, Prometheus, and Chaos Mesh will NOT be removed" in result.output
    assert "[1/3] Removing namespace my-app" in result.output
    assert "has been fully removed" in result.output


def test_destroy_step_failure_stops_and_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    monkeypatch.setattr(preflight, "ensure_cluster_ready", lambda **k: None)

    def failing_delete(*a: object, **k: object) -> None:
        raise NexusError(what="delete failed", why="connection lost")

    monkeypatch.setattr(kubectl, "delete", failing_delete)

    result = runner.invoke(app, ["destroy"], input="my-app\n")
    assert result.exit_code != 0
    assert "connection lost" in result.output


def test_destroy_is_idempotent_when_run_twice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # kubectl.delete itself absorbs "already gone" (see test_kubectl.py); this
    # confirms destroy's step loop treats a clean return as success both times.
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    monkeypatch.setattr(preflight, "ensure_cluster_ready", lambda **k: None)
    monkeypatch.setattr(kubectl, "delete", lambda *a, **k: None)

    result = runner.invoke(app, ["destroy"], input="my-app\n")
    assert result.exit_code == 0, result.output
    result2 = runner.invoke(app, ["destroy"], input="my-app\n")
    assert result2.exit_code == 0, result2.output


def test_destroy_steps_include_monitoring_when_enabled() -> None:
    cfg = _minimal_config(monitoring=True, chaos=False)
    labels = [s[0] for s in destroy_module.destroy_steps(cfg)]
    assert any("monitoring" in label.lower() for label in labels)
    assert not any("chaos" in label.lower() for label in labels)


def test_destroy_steps_include_chaos_when_enabled() -> None:
    cfg = _minimal_config(monitoring=False, chaos=True)
    labels = [s[0] for s in destroy_module.destroy_steps(cfg)]
    assert any("chaos" in label.lower() for label in labels)


def test_destroy_steps_exclude_monitoring_and_chaos_when_disabled() -> None:
    cfg = _minimal_config(monitoring=False, chaos=False)
    labels = [s[0] for s in destroy_module.destroy_steps(cfg)]
    assert len(labels) == 2  # namespace + argocd app only
