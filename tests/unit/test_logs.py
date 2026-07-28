"""Tests for the `nexus logs` command (PRD §7.8)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from kubernetes.client.exceptions import ApiException
from typer.testing import CliRunner

from nexus_cli.core import logs as core_logs
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


def _fake_pod(name: str) -> SimpleNamespace:
    return SimpleNamespace(metadata=SimpleNamespace(name=name))


def _fake_response(text: str) -> SimpleNamespace:
    """Mimics the raw urllib3 HTTPResponse returned with _preload_content=False."""
    return SimpleNamespace(data=text.encode("utf-8"))


def _setup_common(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    monkeypatch.setattr(preflight, "ensure_cluster_ready", lambda **k: None)
    monkeypatch.setattr(core_logs.k8s_config, "load_kube_config", lambda: None)


def test_logs_preflight_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)

    def fail(**k: object) -> None:
        raise NexusError(what="cluster not reachable")

    monkeypatch.setattr(preflight, "ensure_cluster_ready", fail)
    result = runner.invoke(app, ["logs"])
    assert result.exit_code != 0
    assert "cluster not reachable" in result.output


def test_logs_kubeconfig_load_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    monkeypatch.setattr(preflight, "ensure_cluster_ready", lambda **k: None)

    def raise_err() -> None:
        raise RuntimeError("no kubeconfig")

    monkeypatch.setattr(core_logs.k8s_config, "load_kube_config", raise_err)
    result = runner.invoke(app, ["logs"])
    assert result.exit_code != 0
    assert "Could not load a Kubernetes config" in result.output


def test_logs_prefixes_lines_by_pod(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_common(tmp_path, monkeypatch)

    pods = SimpleNamespace(items=[_fake_pod("my-app-def456"), _fake_pod("my-app-abc123")])
    log_texts = {
        "my-app-abc123": "line one\nline two",
        "my-app-def456": "hello\nworld",
    }

    fake_api = SimpleNamespace(
        list_namespaced_pod=lambda namespace, label_selector=None: pods,
        read_namespaced_pod_log=(
            lambda name, namespace, tail_lines=None, _preload_content=True: _fake_response(
                log_texts[name]
            )
        ),
    )
    monkeypatch.setattr(core_logs.k8s_client, "CoreV1Api", lambda: fake_api)

    result = runner.invoke(app, ["logs"])
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    # sorted order: abc123 before def456
    assert lines.index("my-app-abc123 | line one") < lines.index("my-app-def456 | hello")
    assert "my-app-abc123 | line two" in result.output
    assert "my-app-def456 | world" in result.output


def test_logs_respects_tail_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_common(tmp_path, monkeypatch)

    pods = SimpleNamespace(items=[_fake_pod("my-app-abc123")])
    seen_tail: dict[str, int] = {}

    def read_log(
        name: str, namespace: str, tail_lines: int | None = None, _preload_content: bool = True
    ) -> SimpleNamespace:
        seen_tail["tail_lines"] = tail_lines
        return _fake_response("a line")

    fake_api = SimpleNamespace(
        list_namespaced_pod=lambda namespace, label_selector=None: pods,
        read_namespaced_pod_log=read_log,
    )
    monkeypatch.setattr(core_logs.k8s_client, "CoreV1Api", lambda: fake_api)

    result = runner.invoke(app, ["logs", "--tail", "5"])
    assert result.exit_code == 0, result.output
    assert seen_tail["tail_lines"] == 5


def test_logs_no_pods_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_common(tmp_path, monkeypatch)

    pods = SimpleNamespace(items=[])
    fake_api = SimpleNamespace(
        list_namespaced_pod=lambda namespace, label_selector=None: pods,
        read_namespaced_pod_log=(
            lambda name, namespace, tail_lines=None, _preload_content=True: _fake_response("")
        ),
    )
    monkeypatch.setattr(core_logs.k8s_client, "CoreV1Api", lambda: fake_api)

    result = runner.invoke(app, ["logs"])
    assert result.exit_code == 0, result.output
    assert "No pods found" in result.output


def test_logs_continues_after_one_pod_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_common(tmp_path, monkeypatch)

    pods = SimpleNamespace(items=[_fake_pod("my-app-abc123"), _fake_pod("my-app-def456")])

    def read_log(
        name: str, namespace: str, tail_lines: int | None = None, _preload_content: bool = True
    ) -> SimpleNamespace:
        if name == "my-app-abc123":
            raise ApiException(reason="ContainerCreating")
        return _fake_response("all good")

    fake_api = SimpleNamespace(
        list_namespaced_pod=lambda namespace, label_selector=None: pods,
        read_namespaced_pod_log=read_log,
    )
    monkeypatch.setattr(core_logs.k8s_client, "CoreV1Api", lambda: fake_api)

    result = runner.invoke(app, ["logs"])
    assert result.exit_code == 0, result.output
    assert "Could not fetch logs for my-app-abc123" in result.output
    assert "my-app-def456 | all good" in result.output
