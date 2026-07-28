"""Unit tests for nexus_cli.core.logs (mocked kubernetes SDK; no live cluster)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from kubernetes.client.exceptions import ApiException

from nexus_cli.core import logs
from nexus_cli.core.output import NexusError


def _fake_pod(name: str) -> SimpleNamespace:
    return SimpleNamespace(metadata=SimpleNamespace(name=name))


def _fake_response(text: str) -> SimpleNamespace:
    """Mimics the raw urllib3 HTTPResponse returned with _preload_content=False."""
    return SimpleNamespace(data=text.encode("utf-8"))


def _install_fake_api(monkeypatch: pytest.MonkeyPatch, api: SimpleNamespace) -> None:
    monkeypatch.setattr(logs.k8s_config, "load_kube_config", lambda: None)
    monkeypatch.setattr(logs.k8s_client, "CoreV1Api", lambda: api)


def test_load_kube_config_raises_nexus_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_err() -> None:
        raise RuntimeError("no kubeconfig")

    monkeypatch.setattr(logs.k8s_config, "load_kube_config", raise_err)
    with pytest.raises(NexusError) as exc_info:
        logs.load_kube_config()
    assert "Could not load a Kubernetes config" in exc_info.value.what
    assert exc_info.value.fix


def test_get_pod_logs_returns_sorted_pods_with_split_lines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pods = SimpleNamespace(items=[_fake_pod("my-app-def456"), _fake_pod("my-app-abc123")])
    texts = {"my-app-abc123": "line one\nline two", "my-app-def456": "hello"}
    _install_fake_api(
        monkeypatch,
        SimpleNamespace(
            list_namespaced_pod=lambda namespace, label_selector=None: pods,
            read_namespaced_pod_log=(
                lambda name, namespace, tail_lines=None, _preload_content=True: _fake_response(
                    texts[name]
                )
            ),
        ),
    )

    result = logs.get_pod_logs("my-app", "my-app")
    assert [entry.pod for entry in result] == ["my-app-abc123", "my-app-def456"]
    assert result[0].lines == ["line one", "line two"]
    assert result[0].error is None


def test_get_pod_logs_decodes_bytes_rather_than_stringifying_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression guard for the kubernetes==36.0.3 deserialization bug.

    The client's default path returns the *repr* of a bytes object — a literal
    "b'...\\n...'" string with escaped newlines. Reading `.data` from the raw
    response and decoding it ourselves is what keeps real newlines real.
    """
    pods = SimpleNamespace(items=[_fake_pod("my-app-abc123")])
    seen: dict[str, object] = {}

    def read_log(
        name: str, namespace: str, tail_lines: int | None = None, _preload_content: bool = True
    ) -> SimpleNamespace:
        seen["_preload_content"] = _preload_content
        return _fake_response("first\nsecond")

    _install_fake_api(
        monkeypatch,
        SimpleNamespace(
            list_namespaced_pod=lambda namespace, label_selector=None: pods,
            read_namespaced_pod_log=read_log,
        ),
    )

    result = logs.get_pod_logs("my-app", "my-app")
    assert seen["_preload_content"] is False
    assert result[0].lines == ["first", "second"]
    assert not any(line.startswith("b'") for line in result[0].lines)


def test_get_pod_logs_passes_tail_and_label_selector(monkeypatch: pytest.MonkeyPatch) -> None:
    pods = SimpleNamespace(items=[_fake_pod("my-app-abc123")])
    seen: dict[str, object] = {}

    def list_pods(namespace: str, label_selector: str | None = None) -> SimpleNamespace:
        seen["namespace"] = namespace
        seen["label_selector"] = label_selector
        return pods

    def read_log(
        name: str, namespace: str, tail_lines: int | None = None, _preload_content: bool = True
    ) -> SimpleNamespace:
        seen["tail_lines"] = tail_lines
        return _fake_response("a line")

    _install_fake_api(
        monkeypatch,
        SimpleNamespace(list_namespaced_pod=list_pods, read_namespaced_pod_log=read_log),
    )

    logs.get_pod_logs("my-app", "my-app", tail=7)
    assert seen["namespace"] == "my-app"
    assert seen["label_selector"] == "app=my-app"
    assert seen["tail_lines"] == 7


def test_get_pod_logs_reports_per_pod_failure_in_band(monkeypatch: pytest.MonkeyPatch) -> None:
    """One unreadable pod must not cost us the others' logs."""
    pods = SimpleNamespace(items=[_fake_pod("my-app-abc123"), _fake_pod("my-app-def456")])

    def read_log(
        name: str, namespace: str, tail_lines: int | None = None, _preload_content: bool = True
    ) -> SimpleNamespace:
        if name == "my-app-abc123":
            raise ApiException(reason="ContainerCreating")
        return _fake_response("all good")

    _install_fake_api(
        monkeypatch,
        SimpleNamespace(
            list_namespaced_pod=lambda namespace, label_selector=None: pods,
            read_namespaced_pod_log=read_log,
        ),
    )

    result = logs.get_pod_logs("my-app", "my-app")
    assert result[0].error == "ContainerCreating"
    assert result[0].lines == []
    assert result[1].lines == ["all good"]


def test_get_pod_logs_empty_when_no_pods(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_api(
        monkeypatch,
        SimpleNamespace(
            list_namespaced_pod=lambda namespace, label_selector=None: SimpleNamespace(items=[]),
            read_namespaced_pod_log=lambda *a, **k: _fake_response(""),
        ),
    )
    assert logs.get_pod_logs("my-app", "my-app") == []


def test_get_pod_logs_drops_blank_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    pods = SimpleNamespace(items=[_fake_pod("my-app-abc123")])
    _install_fake_api(
        monkeypatch,
        SimpleNamespace(
            list_namespaced_pod=lambda namespace, label_selector=None: pods,
            read_namespaced_pod_log=(
                lambda name, namespace, tail_lines=None, _preload_content=True: _fake_response(
                    "one\n\ntwo\n"
                )
            ),
        ),
    )
    assert logs.get_pod_logs("my-app", "my-app")[0].lines == ["one", "two"]
