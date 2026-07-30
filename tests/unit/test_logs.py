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


# --- nexus logs --follow ---
#
# follow_pod_logs uses kubernetes.watch.Watch().stream(read_namespaced_pod_log,
# ..., follow=True) — verified directly against the installed kubernetes
# package's source (Watch.get_watch_argument_name inspects the wrapped
# function's docstring for a "follow" parameter, and Watch.stream() yields
# raw lines rather than trying to unmarshal them as WatchEvent JSON when it
# finds one) before relying on it here. _FakeWatch mirrors that real
# contract: .stream(func, **kwargs) returns an iterable of raw strings, not
# a real network stream — no threading race in tests, since a fake iterable
# just runs to completion immediately when a follower thread starts.


class _FakeWatch:
    def __init__(self, lines_by_pod: dict[str, list[str]]) -> None:
        self._lines_by_pod = lines_by_pod

    def stream(self, func: object, **kwargs: object):  # noqa: ANN201
        pod_name = kwargs["name"]
        assert kwargs.get("follow") is True
        return iter(self._lines_by_pod.get(pod_name, []))  # type: ignore[arg-type]


def _patch_watch(monkeypatch: pytest.MonkeyPatch, lines_by_pod: dict[str, list[str]]) -> None:
    monkeypatch.setattr(core_logs.k8s_watch, "Watch", lambda: _FakeWatch(lines_by_pod))


def test_logs_follow_streams_lines_from_all_pods_prefixed_by_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_common(tmp_path, monkeypatch)
    pods = SimpleNamespace(items=[_fake_pod("my-app-abc123"), _fake_pod("my-app-def456")])
    fake_api = SimpleNamespace(
        list_namespaced_pod=lambda namespace, label_selector=None: pods,
        read_namespaced_pod_log=lambda **k: None,  # never actually called; Watch owns it
    )
    monkeypatch.setattr(core_logs.k8s_client, "CoreV1Api", lambda: fake_api)
    _patch_watch(
        monkeypatch,
        {"my-app-abc123": ["line one", "line two"], "my-app-def456": ["hello"]},
    )

    result = runner.invoke(app, ["logs", "--follow"])
    assert result.exit_code == 0, result.output
    assert "Following logs for 'my-app'" in result.output
    assert "my-app-abc123 | line one" in result.output
    assert "my-app-abc123 | line two" in result.output
    assert "my-app-def456 | hello" in result.output


def test_logs_follow_short_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_common(tmp_path, monkeypatch)
    pods = SimpleNamespace(items=[_fake_pod("my-app-abc123")])
    fake_api = SimpleNamespace(
        list_namespaced_pod=lambda namespace, label_selector=None: pods,
        read_namespaced_pod_log=lambda **k: None,
    )
    monkeypatch.setattr(core_logs.k8s_client, "CoreV1Api", lambda: fake_api)
    _patch_watch(monkeypatch, {"my-app-abc123": ["a line"]})

    result = runner.invoke(app, ["logs", "-f"])
    assert result.exit_code == 0, result.output
    assert "my-app-abc123 | a line" in result.output


def test_logs_follow_no_pods_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_common(tmp_path, monkeypatch)
    pods = SimpleNamespace(items=[])
    fake_api = SimpleNamespace(
        list_namespaced_pod=lambda namespace, label_selector=None: pods,
        read_namespaced_pod_log=lambda **k: None,
    )
    monkeypatch.setattr(core_logs.k8s_client, "CoreV1Api", lambda: fake_api)
    _patch_watch(monkeypatch, {})

    result = runner.invoke(app, ["logs", "--follow"])
    assert result.exit_code == 0, result.output
    assert "No pods found" in result.output


def test_logs_follow_preflight_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)

    def fail(**k: object) -> None:
        raise NexusError(what="cluster not reachable")

    monkeypatch.setattr(preflight, "ensure_cluster_ready", fail)
    result = runner.invoke(app, ["logs", "--follow"])
    assert result.exit_code != 0
    assert "cluster not reachable" in result.output


def test_logs_follow_stream_error_reports_in_band(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One pod's stream ending in an ApiException shouldn't crash the whole
    follow session — mirrors get_pod_logs' per-pod error handling.
    """
    _setup_common(tmp_path, monkeypatch)
    pods = SimpleNamespace(items=[_fake_pod("my-app-abc123")])
    fake_api = SimpleNamespace(
        list_namespaced_pod=lambda namespace, label_selector=None: pods,
        read_namespaced_pod_log=lambda **k: None,
    )
    monkeypatch.setattr(core_logs.k8s_client, "CoreV1Api", lambda: fake_api)

    class _RaisingWatch:
        def stream(self, func: object, **kwargs: object):  # noqa: ANN201
            raise ApiException(reason="pod terminated")

    monkeypatch.setattr(core_logs.k8s_watch, "Watch", lambda: _RaisingWatch())

    result = runner.invoke(app, ["logs", "--follow"])
    assert result.exit_code == 0, result.output
    assert "my-app-abc123 | <log stream ended: pod terminated>" in result.output


# --- core_logs.follow_pod_logs directly (return value, no-pods fast path) ---


def test_follow_pod_logs_returns_followed_pod_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(core_logs, "load_kube_config", lambda: None)
    pods = SimpleNamespace(items=[_fake_pod("b"), _fake_pod("a")])
    fake_api = SimpleNamespace(
        list_namespaced_pod=lambda namespace, label_selector=None: pods,
        read_namespaced_pod_log=lambda **k: None,
    )
    monkeypatch.setattr(core_logs.k8s_client, "CoreV1Api", lambda: fake_api)
    monkeypatch.setattr(core_logs.k8s_watch, "Watch", lambda: _FakeWatch({}))

    result = core_logs.follow_pod_logs(
        "my-app", "my-app", on_line=lambda pod, line: None
    )
    assert result == ["a", "b"]  # sorted


def test_follow_pod_logs_no_pods_returns_empty_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(core_logs, "load_kube_config", lambda: None)
    pods = SimpleNamespace(items=[])
    fake_api = SimpleNamespace(
        list_namespaced_pod=lambda namespace, label_selector=None: pods,
        read_namespaced_pod_log=lambda **k: None,
    )
    monkeypatch.setattr(core_logs.k8s_client, "CoreV1Api", lambda: fake_api)

    result = core_logs.follow_pod_logs(
        "my-app", "my-app", on_line=lambda pod, line: None
    )
    assert result == []
