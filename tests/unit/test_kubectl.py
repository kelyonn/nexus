"""Unit tests for nexus_cli.core.kubectl (mocked subprocess; no live cluster)."""

from __future__ import annotations

import json
import subprocess

import pytest

from nexus_cli.core import kubectl
from nexus_cli.core.output import NexusError


class _FakeCompleted:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _patch_which(monkeypatch: pytest.MonkeyPatch, present: bool) -> None:
    path = "/usr/local/bin/kubectl" if present else None
    monkeypatch.setattr(kubectl.shutil, "which", lambda name: path)


def test_is_installed_true(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_which(monkeypatch, True)
    assert kubectl.is_installed() is True


def test_is_installed_false(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_which(monkeypatch, False)
    assert kubectl.is_installed() is False


def test_run_raises_when_not_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_which(monkeypatch, False)
    with pytest.raises(NexusError) as exc_info:
        kubectl.run(["get", "nodes"])
    assert "not installed" in exc_info.value.what


def test_run_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_which(monkeypatch, True)
    monkeypatch.setattr(
        kubectl.subprocess, "run", lambda *a, **k: _FakeCompleted(returncode=0, stdout="ok")
    )
    result = kubectl.run(["get", "nodes"])
    assert result.stdout == "ok"


def test_run_failure_raises_nexus_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_which(monkeypatch, True)
    monkeypatch.setattr(
        kubectl.subprocess, "run", lambda *a, **k: _FakeCompleted(returncode=1, stderr="boom")
    )
    with pytest.raises(NexusError) as exc_info:
        kubectl.run(["get", "nodes"])
    assert "boom" in exc_info.value.why


def test_run_check_false_does_not_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_which(monkeypatch, True)
    monkeypatch.setattr(
        kubectl.subprocess, "run", lambda *a, **k: _FakeCompleted(returncode=1, stderr="boom")
    )
    result = kubectl.run(["get", "nodes"], check=False)
    assert result.returncode == 1


def test_run_timeout_raises_nexus_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_which(monkeypatch, True)

    def raise_timeout(*a: object, **k: object) -> None:
        raise subprocess.TimeoutExpired(cmd="kubectl", timeout=15)

    monkeypatch.setattr(kubectl.subprocess, "run", raise_timeout)
    with pytest.raises(NexusError) as exc_info:
        kubectl.run(["get", "nodes"])
    assert "timed out" in exc_info.value.what


def test_version_client_parses_json(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_which(monkeypatch, True)
    payload = json.dumps({"clientVersion": {"gitVersion": "v1.29.0"}})
    monkeypatch.setattr(
        kubectl.subprocess, "run", lambda *a, **k: _FakeCompleted(returncode=0, stdout=payload)
    )
    assert kubectl.version_client() == "v1.29.0"


def test_version_client_none_when_not_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_which(monkeypatch, False)
    assert kubectl.version_client() is None


def test_version_client_none_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_which(monkeypatch, True)
    monkeypatch.setattr(kubectl.subprocess, "run", lambda *a, **k: _FakeCompleted(returncode=1))
    assert kubectl.version_client() is None


def test_current_context(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_which(monkeypatch, True)
    monkeypatch.setattr(
        kubectl.subprocess, "run", lambda *a, **k: _FakeCompleted(returncode=0, stdout="minikube\n")
    )
    assert kubectl.current_context() == "minikube"


def test_current_context_none_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_which(monkeypatch, True)
    monkeypatch.setattr(kubectl.subprocess, "run", lambda *a, **k: _FakeCompleted(returncode=1))
    assert kubectl.current_context() is None


def test_cluster_reachable_true(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_which(monkeypatch, True)
    monkeypatch.setattr(kubectl.subprocess, "run", lambda *a, **k: _FakeCompleted(returncode=0))
    assert kubectl.cluster_reachable() is True


def test_cluster_reachable_false_when_not_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_which(monkeypatch, False)
    assert kubectl.cluster_reachable() is False


def test_get_json_builds_correct_args_and_parses(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_which(monkeypatch, True)
    captured: dict[str, list[str]] = {}

    def fake_run(args: list[str], **kwargs: object) -> _FakeCompleted:
        captured["args"] = args
        return _FakeCompleted(returncode=0, stdout=json.dumps({"items": []}))

    monkeypatch.setattr(kubectl.subprocess, "run", fake_run)
    result = kubectl.get_json("pods", namespace="my-app")
    assert result == {"items": []}
    assert captured["args"] == ["kubectl", "get", "pods", "-n", "my-app", "-o", "json"]


def test_get_json_with_name(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_which(monkeypatch, True)
    captured: dict[str, list[str]] = {}

    def fake_run(args: list[str], **kwargs: object) -> _FakeCompleted:
        captured["args"] = args
        return _FakeCompleted(returncode=0, stdout="{}")

    monkeypatch.setattr(kubectl.subprocess, "run", fake_run)
    kubectl.get_json("deployment", namespace="my-app", name="my-app")
    assert captured["args"] == [
        "kubectl",
        "get",
        "deployment",
        "my-app",
        "-n",
        "my-app",
        "-o",
        "json",
    ]


def test_get_json_all_namespaces(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_which(monkeypatch, True)
    captured: dict[str, list[str]] = {}

    def fake_run(args: list[str], **kwargs: object) -> _FakeCompleted:
        captured["args"] = args
        return _FakeCompleted(returncode=0, stdout="{}")

    monkeypatch.setattr(kubectl.subprocess, "run", fake_run)
    kubectl.get_json("application", all_namespaces=True)
    assert captured["args"] == ["kubectl", "get", "application", "-A", "-o", "json"]


def test_apply_manifest_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_which(monkeypatch, True)
    captured: dict[str, object] = {}

    def fake_run(*args: object, **kwargs: object) -> _FakeCompleted:
        captured["input"] = kwargs.get("input")
        return _FakeCompleted(returncode=0, stdout="applied")

    monkeypatch.setattr(kubectl.subprocess, "run", fake_run)
    result = kubectl.apply_manifest("kind: Namespace")
    assert result.stdout == "applied"
    assert captured["input"] == "kind: Namespace"


def test_apply_manifest_failure_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_which(monkeypatch, True)
    monkeypatch.setattr(
        kubectl.subprocess,
        "run",
        lambda *a, **k: _FakeCompleted(returncode=1, stderr="invalid yaml"),
    )
    with pytest.raises(NexusError) as exc_info:
        kubectl.apply_manifest("bad")
    assert "invalid yaml" in exc_info.value.why


def test_delete_builds_correct_args(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_which(monkeypatch, True)
    captured: dict[str, list[str]] = {}

    def fake_run(args: list[str], **kwargs: object) -> _FakeCompleted:
        captured["args"] = args
        return _FakeCompleted(returncode=0)

    monkeypatch.setattr(kubectl.subprocess, "run", fake_run)
    kubectl.delete("namespace", "my-app")
    assert captured["args"] == [
        "kubectl",
        "delete",
        "namespace",
        "my-app",
        "--ignore-not-found=true",
    ]


def test_delete_treats_missing_object_as_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_which(monkeypatch, True)
    monkeypatch.setattr(kubectl.subprocess, "run", lambda *a, **k: _FakeCompleted(returncode=0))
    result = kubectl.delete("namespace", "my-app")
    assert result.returncode == 0


def test_delete_treats_missing_resource_type_as_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_which(monkeypatch, True)
    monkeypatch.setattr(
        kubectl.subprocess,
        "run",
        lambda *a, **k: _FakeCompleted(
            returncode=1, stderr="error: the server doesn't have a resource type \"application\""
        ),
    )
    result = kubectl.delete("application", "my-app", namespace="argocd")
    assert result.returncode == 1  # returned, not raised — treated as already gone


def test_delete_raises_on_real_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_which(monkeypatch, True)
    monkeypatch.setattr(
        kubectl.subprocess,
        "run",
        lambda *a, **k: _FakeCompleted(returncode=1, stderr="connection refused"),
    )
    with pytest.raises(NexusError) as exc_info:
        kubectl.delete("namespace", "my-app")
    assert "connection refused" in exc_info.value.why


def test_delete_raises_on_real_failure_even_with_ignore_not_found_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_which(monkeypatch, True)
    monkeypatch.setattr(
        kubectl.subprocess,
        "run",
        lambda *a, **k: _FakeCompleted(
            returncode=1, stderr="error: the server doesn't have a resource type \"application\""
        ),
    )
    with pytest.raises(NexusError):
        kubectl.delete("application", "my-app", namespace="argocd", ignore_not_found=False)


def test_is_missing_resource_type_recognizes_both_phrasings() -> None:
    assert kubectl.is_missing_resource_type(
        'the server doesn\'t have a resource type "application"'
    )
    assert kubectl.is_missing_resource_type(
        "error: the server could not find the requested resource"
    )


def test_is_missing_resource_type_is_case_insensitive() -> None:
    assert kubectl.is_missing_resource_type("The Server Could Not Find The Requested Resource")


def test_is_missing_resource_type_false_for_other_errors() -> None:
    assert not kubectl.is_missing_resource_type("Unable to connect to the server: i/o timeout")
    assert not kubectl.is_missing_resource_type('applications "my-app" not found')
    assert not kubectl.is_missing_resource_type("")


def test_is_not_found_recognizes_kubectl_phrasings() -> None:
    assert kubectl.is_not_found('Error from server (NotFound): deployments.apps "x" not found')
    assert kubectl.is_not_found('namespaces "my-app" not found')


def test_is_not_found_false_for_permission_and_connectivity_errors() -> None:
    """These must NOT read as 'nothing there' — they're real failures."""
    assert not kubectl.is_not_found('deployments.apps is forbidden: User cannot list resource')
    assert not kubectl.is_not_found("Unable to connect to the server: dial tcp: i/o timeout")
    assert not kubectl.is_not_found("")


def test_namespace_exists_true(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_which(monkeypatch, True)
    monkeypatch.setattr(kubectl.subprocess, "run", lambda *a, **k: _FakeCompleted(returncode=0))
    assert kubectl.namespace_exists("my-app") is True


def test_namespace_exists_false(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_which(monkeypatch, True)
    monkeypatch.setattr(kubectl.subprocess, "run", lambda *a, **k: _FakeCompleted(returncode=1))
    assert kubectl.namespace_exists("my-app") is False


def test_resource_exists_true(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_which(monkeypatch, True)
    captured: dict[str, list[str]] = {}

    def fake_run(args: list[str], **kwargs: object) -> _FakeCompleted:
        captured["args"] = args
        return _FakeCompleted(returncode=0)

    monkeypatch.setattr(kubectl.subprocess, "run", fake_run)
    assert kubectl.resource_exists("servicemonitor", "my-app", namespace="my-app") is True
    assert captured["args"] == ["kubectl", "get", "servicemonitor", "my-app", "-n", "my-app"]


def test_resource_exists_false(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_which(monkeypatch, True)
    monkeypatch.setattr(kubectl.subprocess, "run", lambda *a, **k: _FakeCompleted(returncode=1))
    assert kubectl.resource_exists("servicemonitor", "my-app", namespace="my-app") is False


def test_can_i_true(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_which(monkeypatch, True)
    captured: dict[str, list[str]] = {}

    def fake_run(args: list[str], **kwargs: object) -> _FakeCompleted:
        captured["args"] = args
        return _FakeCompleted(returncode=0, stdout="yes\n")

    monkeypatch.setattr(kubectl.subprocess, "run", fake_run)
    assert kubectl.can_i("create", "namespaces") is True
    assert captured["args"] == ["kubectl", "auth", "can-i", "create", "namespaces"]


def test_can_i_false_on_no(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_which(monkeypatch, True)
    monkeypatch.setattr(
        kubectl.subprocess, "run", lambda *a, **k: _FakeCompleted(returncode=1, stdout="no\n")
    )
    assert kubectl.can_i("create", "namespaces") is False


def test_can_i_all_namespaces_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_which(monkeypatch, True)
    captured: dict[str, list[str]] = {}

    def fake_run(args: list[str], **kwargs: object) -> _FakeCompleted:
        captured["args"] = args
        return _FakeCompleted(returncode=0, stdout="yes\n")

    monkeypatch.setattr(kubectl.subprocess, "run", fake_run)
    kubectl.can_i("create", "deployments", all_namespaces=True)
    assert captured["args"] == ["kubectl", "auth", "can-i", "create", "deployments", "-A"]


def test_can_i_raises_when_not_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_which(monkeypatch, False)
    with pytest.raises(NexusError, match="not installed"):
        kubectl.can_i("create", "namespaces")
