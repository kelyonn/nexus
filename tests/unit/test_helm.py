"""Unit tests for nexus_cli.core.helm (mocked subprocess; no live cluster)."""

from __future__ import annotations

import json
import subprocess

import pytest

from nexus_cli.core import helm
from nexus_cli.core.output import NexusError


class _FakeCompleted:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _patch_which(monkeypatch: pytest.MonkeyPatch, present: bool) -> None:
    path = "/usr/local/bin/helm" if present else None
    monkeypatch.setattr(helm.shutil, "which", lambda name: path)


def test_is_installed_true(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_which(monkeypatch, True)
    assert helm.is_installed() is True


def test_is_installed_false(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_which(monkeypatch, False)
    assert helm.is_installed() is False


def test_version_returns_none_when_not_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_which(monkeypatch, False)
    assert helm.version() is None


def test_version_parses_output(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_which(monkeypatch, True)
    monkeypatch.setattr(
        helm.subprocess, "run", lambda *a, **k: _FakeCompleted(returncode=0, stdout="v3.14.1+g\n")
    )
    assert helm.version() == "v3.14.1+g"


def test_version_none_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_which(monkeypatch, True)

    def raise_timeout(*a: object, **k: object) -> None:
        raise subprocess.TimeoutExpired(cmd="helm", timeout=15)

    monkeypatch.setattr(helm.subprocess, "run", raise_timeout)
    assert helm.version() is None


def test_list_releases_not_installed_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_which(monkeypatch, False)
    with pytest.raises(NexusError):
        helm.list_releases("argocd")


def test_list_releases_parses_json(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_which(monkeypatch, True)
    payload = json.dumps([{"name": "argocd", "namespace": "argocd"}])
    monkeypatch.setattr(
        helm.subprocess, "run", lambda *a, **k: _FakeCompleted(returncode=0, stdout=payload)
    )
    releases = helm.list_releases("argocd")
    assert releases[0]["name"] == "argocd"


def test_list_releases_empty_output(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_which(monkeypatch, True)
    monkeypatch.setattr(
        helm.subprocess, "run", lambda *a, **k: _FakeCompleted(returncode=0, stdout="")
    )
    assert helm.list_releases("argocd") == []


def test_list_releases_failure_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_which(monkeypatch, True)
    monkeypatch.setattr(
        helm.subprocess,
        "run",
        lambda *a, **k: _FakeCompleted(returncode=1, stderr="no such namespace"),
    )
    with pytest.raises(NexusError):
        helm.list_releases("argocd")


def test_release_exists_true(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_which(monkeypatch, True)
    payload = json.dumps([{"name": "argocd"}])
    monkeypatch.setattr(
        helm.subprocess, "run", lambda *a, **k: _FakeCompleted(returncode=0, stdout=payload)
    )
    assert helm.release_exists("argocd", "argocd") is True


def test_release_exists_false(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_which(monkeypatch, True)
    monkeypatch.setattr(
        helm.subprocess, "run", lambda *a, **k: _FakeCompleted(returncode=0, stdout="[]")
    )
    assert helm.release_exists("argocd", "argocd") is False


def test_upgrade_install_not_installed_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_which(monkeypatch, False)
    with pytest.raises(NexusError):
        helm.upgrade_install("argocd", "argo/argo-cd", namespace="argocd")


def test_upgrade_install_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_which(monkeypatch, True)
    captured: dict[str, list[str]] = {}

    def fake_run(args: list[str], **kwargs: object) -> _FakeCompleted:
        captured["args"] = args
        return _FakeCompleted(returncode=0, stdout="installed")

    monkeypatch.setattr(helm.subprocess, "run", fake_run)
    result = helm.upgrade_install("argocd", "argo/argo-cd", namespace="argocd")
    assert result.stdout == "installed"
    assert "--create-namespace" in captured["args"]


def test_upgrade_install_with_values(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_which(monkeypatch, True)
    captured: dict[str, list[str]] = {}

    def fake_run(args: list[str], **kwargs: object) -> _FakeCompleted:
        captured["args"] = args
        return _FakeCompleted(returncode=0)

    monkeypatch.setattr(helm.subprocess, "run", fake_run)
    helm.upgrade_install("x", "chart", namespace="ns", values={"replicaCount": "3"})
    assert "--set" in captured["args"]
    assert "replicaCount=3" in captured["args"]


def test_upgrade_install_with_chart_version(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_which(monkeypatch, True)
    captured: dict[str, list[str]] = {}

    def fake_run(args: list[str], **kwargs: object) -> _FakeCompleted:
        captured["args"] = args
        return _FakeCompleted(returncode=0)

    monkeypatch.setattr(helm.subprocess, "run", fake_run)
    helm.upgrade_install("x", "chart", namespace="ns", chart_version="1.2.3")
    assert "--version" in captured["args"]
    assert "1.2.3" in captured["args"]


def test_upgrade_install_without_chart_version_omits_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No chart_version -> no --version flag, not `--version None`."""
    _patch_which(monkeypatch, True)
    captured: dict[str, list[str]] = {}

    def fake_run(args: list[str], **kwargs: object) -> _FakeCompleted:
        captured["args"] = args
        return _FakeCompleted(returncode=0)

    monkeypatch.setattr(helm.subprocess, "run", fake_run)
    helm.upgrade_install("x", "chart", namespace="ns")
    assert "--version" not in captured["args"]


def test_upgrade_install_failure_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_which(monkeypatch, True)
    monkeypatch.setattr(
        helm.subprocess,
        "run",
        lambda *a, **k: _FakeCompleted(returncode=1, stderr="chart not found"),
    )
    with pytest.raises(NexusError) as exc_info:
        helm.upgrade_install("x", "bad-chart", namespace="ns")
    assert "chart not found" in exc_info.value.why


def test_upgrade_install_timeout_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_which(monkeypatch, True)

    def raise_timeout(*a: object, **k: object) -> None:
        raise subprocess.TimeoutExpired(cmd="helm", timeout=600)

    monkeypatch.setattr(helm.subprocess, "run", raise_timeout)
    with pytest.raises(NexusError) as exc_info:
        helm.upgrade_install("x", "chart", namespace="ns")
    assert "timed out" in exc_info.value.what


def test_repo_add_not_installed_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_which(monkeypatch, False)
    with pytest.raises(NexusError):
        helm.repo_add("argo", "https://argoproj.github.io/argo-helm")


def test_repo_add_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_which(monkeypatch, True)
    calls: list[list[str]] = []

    def fake_run(args: list[str], **kwargs: object) -> _FakeCompleted:
        calls.append(args)
        return _FakeCompleted(returncode=0)

    monkeypatch.setattr(helm.subprocess, "run", fake_run)
    helm.repo_add("argo", "https://argoproj.github.io/argo-helm")
    assert calls[0][:3] == ["helm", "repo", "add"]
    assert calls[1][:3] == ["helm", "repo", "update"]
