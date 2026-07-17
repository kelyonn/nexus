"""Tests for the `nexus watch` command (PRD §7.4)."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from typer.testing import CliRunner

from nexus_cli.commands import watch as watch_module
from nexus_cli.core import preflight
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


class _FakeWatch:
    def __init__(self, events: Iterable[dict]) -> None:
        self._events = events
        self.stopped = False

    def stream(self, func: object, **kwargs: object) -> Iterable[dict]:
        yield from self._events

    def stop(self) -> None:
        self.stopped = True


def _fake_pod_event(name: str, phase: str) -> dict[str, Any]:
    pod = SimpleNamespace(metadata=SimpleNamespace(name=name), status=SimpleNamespace(phase=phase))
    return {"object": pod}


def test_watch_preflight_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)

    def fail(**k: object) -> None:
        raise NexusError(what="cluster not reachable")

    monkeypatch.setattr(preflight, "ensure_cluster_ready", fail)
    result = runner.invoke(app, ["watch"])
    assert result.exit_code != 0
    assert "cluster not reachable" in result.output


def test_watch_streams_pod_events(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    monkeypatch.setattr(preflight, "ensure_cluster_ready", lambda **k: None)
    monkeypatch.setattr(watch_module.k8s_config, "load_kube_config", lambda: None)
    monkeypatch.setattr(
        watch_module.k8s_client, "CoreV1Api", lambda: SimpleNamespace(list_namespaced_pod=None)
    )
    events = [
        _fake_pod_event("my-app-abc123", "Running"),
        _fake_pod_event("my-app-def456", "Pending"),
    ]
    monkeypatch.setattr(watch_module.k8s_watch, "Watch", lambda: _FakeWatch(events))

    result = runner.invoke(app, ["watch"])
    assert result.exit_code == 0, result.output
    assert "my-app-abc123" in result.output
    assert "Running" in result.output
    assert "my-app-def456" in result.output
    assert "Pending" in result.output


def test_watch_handles_keyboard_interrupt_cleanly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    monkeypatch.setattr(preflight, "ensure_cluster_ready", lambda **k: None)
    monkeypatch.setattr(watch_module.k8s_config, "load_kube_config", lambda: None)
    monkeypatch.setattr(
        watch_module.k8s_client, "CoreV1Api", lambda: SimpleNamespace(list_namespaced_pod=None)
    )

    class _InterruptingWatch(_FakeWatch):
        def stream(self, func: object, **kwargs: object) -> Iterable[dict]:
            yield _fake_pod_event("my-app-abc123", "Running")
            raise KeyboardInterrupt

    monkeypatch.setattr(watch_module.k8s_watch, "Watch", lambda: _InterruptingWatch([]))

    result = runner.invoke(app, ["watch"])
    assert result.exit_code == 0, result.output
    assert "Stopped watching" in result.output


def test_watch_kubeconfig_load_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    monkeypatch.setattr(preflight, "ensure_cluster_ready", lambda **k: None)

    def raise_err() -> None:
        raise RuntimeError("no kubeconfig")

    monkeypatch.setattr(watch_module.k8s_config, "load_kube_config", raise_err)
    result = runner.invoke(app, ["watch"])
    assert result.exit_code != 0
    assert "Could not load a Kubernetes config" in result.output
