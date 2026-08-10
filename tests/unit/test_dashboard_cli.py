"""Tests for the `nexus dashboard` command (mocked core.dashboard; no real
servers, no live cluster)."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from nexus_cli.commands import dashboard as dashboard_module
from nexus_cli.core import kubectl
from nexus_cli.core.output import NexusError
from nexus_cli.main import app

runner = CliRunner()
cd = dashboard_module.core_dashboard  # short alias, keeps patch lines under 100 cols


class _FakeProc:
    def __init__(self, name: str) -> None:
        self.name = name

    def wait(self) -> int:
        return 0


class _FakeBrowser:
    def __init__(self, calls: dict[str, object]) -> None:
        self._calls = calls

    def open(self, url: str) -> None:
        self._calls["opened_url"] = url


def _patch_happy_path(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    calls: dict[str, object] = {}
    monkeypatch.setattr(cd, "check_dashboard_deps_installed", lambda: None)
    monkeypatch.setattr(cd, "check_backend_source_present", lambda: None)
    monkeypatch.setattr(cd, "check_frontend_built", lambda: None)
    monkeypatch.setattr(kubectl, "cluster_reachable", lambda: True)
    monkeypatch.setattr(cd, "generate_token", lambda: "test-token")

    def start_backend(token: str) -> _FakeProc:
        calls["backend_proc"] = _FakeProc("backend")
        return calls["backend_proc"]

    monkeypatch.setattr(cd, "start_backend", start_backend)
    monkeypatch.setattr(cd, "start_grafana_port_forward", lambda: None)
    monkeypatch.setattr(cd, "grafana_admin_credentials", lambda: None)
    monkeypatch.setattr(cd, "start_prometheus_port_forward", lambda: None)
    monkeypatch.setattr(cd, "wait_for_backend_ready", lambda: None)
    monkeypatch.setattr(cd, "dashboard_url", lambda token: f"http://x/?token={token}")
    monkeypatch.setattr(dashboard_module, "webbrowser", _FakeBrowser(calls))
    monkeypatch.setattr(
        cd, "shutdown", lambda *procs: calls.setdefault("shutdown_called_with", procs)
    )
    return calls


def test_dashboard_missing_deps_reports_fix(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail() -> None:
        raise NexusError(
            what="Missing dashboard dependencies: fastapi.",
            fix='pip install "nexus-gitops[dashboard]"',
        )

    monkeypatch.setattr(cd, "check_dashboard_deps_installed", fail)
    result = runner.invoke(app, ["dashboard"])
    assert result.exit_code != 0
    assert "Missing dashboard dependencies" in result.output


def test_dashboard_missing_backend_source_reports_fix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cd, "check_dashboard_deps_installed", lambda: None)

    def fail() -> None:
        raise NexusError(what="Dashboard backend source not found.", fix="Clone the repo.")

    monkeypatch.setattr(cd, "check_backend_source_present", fail)
    result = runner.invoke(app, ["dashboard"])
    assert result.exit_code != 0
    assert "backend source not found" in result.output


def test_dashboard_missing_frontend_build_reports_fix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cd, "check_dashboard_deps_installed", lambda: None)
    monkeypatch.setattr(cd, "check_backend_source_present", lambda: None)

    def fail() -> None:
        raise NexusError(what="Dashboard frontend isn't built.", fix="Run npm run build.")

    monkeypatch.setattr(cd, "check_frontend_built", fail)
    result = runner.invoke(app, ["dashboard"])
    assert result.exit_code != 0
    assert "frontend isn't built" in result.output


def test_dashboard_unreachable_cluster_reports_fix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cd, "check_dashboard_deps_installed", lambda: None)
    monkeypatch.setattr(cd, "check_backend_source_present", lambda: None)
    monkeypatch.setattr(cd, "check_frontend_built", lambda: None)
    monkeypatch.setattr(kubectl, "cluster_reachable", lambda: False)
    result = runner.invoke(app, ["dashboard"])
    assert result.exit_code != 0
    assert "No reachable Kubernetes cluster" in result.output


def test_dashboard_happy_path_opens_browser_and_shuts_down_on_ctrl_c(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_happy_path(monkeypatch)

    def raise_keyboard_interrupt() -> int:
        raise KeyboardInterrupt

    original_start_backend = cd.start_backend

    def start_backend_and_arm_interrupt(token: str) -> _FakeProc:
        proc = original_start_backend(token)
        proc.wait = raise_keyboard_interrupt  # type: ignore[method-assign]
        return proc

    monkeypatch.setattr(cd, "start_backend", start_backend_and_arm_interrupt)

    result = runner.invoke(app, ["dashboard"])

    assert result.exit_code == 0, result.output
    assert "Dashboard ready" in result.output
    assert "Shutting down" in result.output
    assert calls["opened_url"] == "http://x/?token=test-token"
    assert calls["shutdown_called_with"] == (calls["backend_proc"],)


def test_dashboard_forwards_grafana_when_available_and_shuts_it_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_happy_path(monkeypatch)

    def start_grafana() -> _FakeProc:
        calls["grafana_proc"] = _FakeProc("grafana")
        return calls["grafana_proc"]

    monkeypatch.setattr(cd, "start_grafana_port_forward", start_grafana)

    def raise_keyboard_interrupt() -> int:
        raise KeyboardInterrupt

    original_start_backend = cd.start_backend

    def start_backend_and_arm_interrupt(token: str) -> _FakeProc:
        proc = original_start_backend(token)
        proc.wait = raise_keyboard_interrupt  # type: ignore[method-assign]
        return proc

    monkeypatch.setattr(cd, "start_backend", start_backend_and_arm_interrupt)

    result = runner.invoke(app, ["dashboard"])

    assert result.exit_code == 0, result.output
    assert "Port-forwarding Grafana" in result.output
    assert calls["shutdown_called_with"] == (
        calls["backend_proc"],
        calls["grafana_proc"],
    )


def test_dashboard_prints_grafana_credentials_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole point of surfacing these is so the user never has to hunt
    for them separately just to get past Grafana's login screen.
    """
    _patch_happy_path(monkeypatch)
    monkeypatch.setattr(cd, "grafana_admin_credentials", lambda: ("admin", "s3cr3t"))

    def raise_keyboard_interrupt() -> int:
        raise KeyboardInterrupt

    original_start_backend = cd.start_backend

    def start_backend_and_arm_interrupt(token: str) -> _FakeProc:
        proc = original_start_backend(token)
        proc.wait = raise_keyboard_interrupt  # type: ignore[method-assign]
        return proc

    monkeypatch.setattr(cd, "start_backend", start_backend_and_arm_interrupt)

    result = runner.invoke(app, ["dashboard"])

    assert result.exit_code == 0, result.output
    assert "Grafana login: admin / s3cr3t" in result.output


def test_dashboard_forwards_prometheus_when_available_and_shuts_it_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_happy_path(monkeypatch)

    def start_prometheus() -> _FakeProc:
        calls["prometheus_proc"] = _FakeProc("prometheus")
        return calls["prometheus_proc"]

    monkeypatch.setattr(cd, "start_prometheus_port_forward", start_prometheus)

    def raise_keyboard_interrupt() -> int:
        raise KeyboardInterrupt

    original_start_backend = cd.start_backend

    def start_backend_and_arm_interrupt(token: str) -> _FakeProc:
        proc = original_start_backend(token)
        proc.wait = raise_keyboard_interrupt  # type: ignore[method-assign]
        return proc

    monkeypatch.setattr(cd, "start_backend", start_backend_and_arm_interrupt)

    result = runner.invoke(app, ["dashboard"])

    assert result.exit_code == 0, result.output
    assert "Port-forwarding Prometheus" in result.output
    assert calls["shutdown_called_with"] == (
        calls["backend_proc"],
        calls["prometheus_proc"],
    )


def test_dashboard_no_prometheus_reports_and_continues(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _patch_happy_path(monkeypatch)

    def raise_keyboard_interrupt() -> int:
        raise KeyboardInterrupt

    original_start_backend = cd.start_backend

    def start_backend_and_arm_interrupt(token: str) -> _FakeProc:
        proc = original_start_backend(token)
        proc.wait = raise_keyboard_interrupt  # type: ignore[method-assign]
        return proc

    monkeypatch.setattr(cd, "start_backend", start_backend_and_arm_interrupt)

    result = runner.invoke(app, ["dashboard"])

    assert result.exit_code == 0, result.output
    assert "No Prometheus found" in result.output
    assert calls["shutdown_called_with"] == (calls["backend_proc"],)


def test_dashboard_no_grafana_reports_and_continues(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _patch_happy_path(monkeypatch)

    def raise_keyboard_interrupt() -> int:
        raise KeyboardInterrupt

    original_start_backend = cd.start_backend

    def start_backend_and_arm_interrupt(token: str) -> _FakeProc:
        proc = original_start_backend(token)
        proc.wait = raise_keyboard_interrupt  # type: ignore[method-assign]
        return proc

    monkeypatch.setattr(cd, "start_backend", start_backend_and_arm_interrupt)

    result = runner.invoke(app, ["dashboard"])

    assert result.exit_code == 0, result.output
    assert "No Grafana found" in result.output
    assert calls["shutdown_called_with"] == (calls["backend_proc"],)


def test_dashboard_backend_not_ready_shuts_down_and_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _patch_happy_path(monkeypatch)

    def fail() -> None:
        raise NexusError(what="Dashboard backend did not become ready within 15s.")

    monkeypatch.setattr(cd, "wait_for_backend_ready", fail)

    result = runner.invoke(app, ["dashboard"])

    assert result.exit_code != 0
    assert "did not become ready" in result.output
    assert calls["shutdown_called_with"] == (calls["backend_proc"],)
    assert "opened_url" not in calls
