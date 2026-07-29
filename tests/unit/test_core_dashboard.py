"""Unit tests for nexus_cli.core.dashboard (mocked subprocess/network; no
real servers, no live cluster).
"""

from __future__ import annotations

import signal
import subprocess
from pathlib import Path

import pytest

from nexus_cli.core import dashboard
from nexus_cli.core.output import NexusError


def test_repo_root_contains_nexus_cli_and_dashboard() -> None:
    root = dashboard.repo_root()
    assert (root / "nexus_cli").is_dir()
    assert (root / "dashboard").is_dir()


def test_backend_dir_and_frontend_dir_are_under_dashboard() -> None:
    assert dashboard.backend_dir() == dashboard.repo_root() / "dashboard" / "backend"
    assert dashboard.frontend_dir() == dashboard.repo_root() / "dashboard" / "frontend"


# --- check_dashboard_deps_installed ---


def test_check_dashboard_deps_installed_passes_when_both_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dashboard.importlib.util, "find_spec", lambda name: object())
    dashboard.check_dashboard_deps_installed()  # must not raise


def test_check_dashboard_deps_installed_names_missing_packages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def find_spec(name: str) -> object | None:
        return None if name == "uvicorn" else object()

    monkeypatch.setattr(dashboard.importlib.util, "find_spec", find_spec)
    with pytest.raises(NexusError) as exc_info:
        dashboard.check_dashboard_deps_installed()
    assert "uvicorn" in exc_info.value.what
    assert "fastapi" not in exc_info.value.what
    assert "dashboard]" in exc_info.value.fix


# --- check_backend_source_present ---


def test_check_backend_source_present_passes_when_main_py_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = tmp_path / "dashboard" / "backend"
    backend.mkdir(parents=True)
    (backend / "main.py").write_text("")
    monkeypatch.setattr(dashboard, "backend_dir", lambda: backend)
    dashboard.check_backend_source_present()  # must not raise


def test_check_backend_source_present_raises_with_clone_fix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dashboard, "backend_dir", lambda: tmp_path / "nowhere")
    with pytest.raises(NexusError) as exc_info:
        dashboard.check_backend_source_present()
    assert "checkout" in exc_info.value.why
    assert "git clone" in exc_info.value.fix.lower() or "clone" in exc_info.value.fix.lower()


# --- check_frontend_ready ---


def test_check_frontend_ready_raises_when_npm_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dashboard.shutil, "which", lambda name: None)
    with pytest.raises(NexusError, match="npm"):
        dashboard.check_frontend_ready()


def test_check_frontend_ready_raises_when_node_modules_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dashboard.shutil, "which", lambda name: "/usr/bin/npm")
    monkeypatch.setattr(dashboard, "frontend_dir", lambda: tmp_path / "frontend")
    with pytest.raises(NexusError) as exc_info:
        dashboard.check_frontend_ready()
    assert "npm install" in exc_info.value.fix


def test_check_frontend_ready_passes_when_node_modules_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frontend = tmp_path / "frontend"
    (frontend / "node_modules").mkdir(parents=True)
    monkeypatch.setattr(dashboard.shutil, "which", lambda name: "/usr/bin/npm")
    monkeypatch.setattr(dashboard, "frontend_dir", lambda: frontend)
    dashboard.check_frontend_ready()  # must not raise


# --- generate_token / dashboard_url ---


def test_generate_token_is_reasonably_long_and_unique() -> None:
    a, b = dashboard.generate_token(), dashboard.generate_token()
    assert a != b
    assert len(a) > 20


def test_dashboard_url_includes_token_and_frontend_port() -> None:
    url = dashboard.dashboard_url("abc123")
    assert url == f"http://localhost:{dashboard.FRONTEND_PORT}/?token=abc123"


# --- start_backend / start_frontend ---


def test_start_backend_passes_token_via_env_and_uses_own_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_popen(args: list[str], **kwargs: object) -> str:
        captured["args"] = args
        captured.update(kwargs)
        return "fake-proc"

    monkeypatch.setattr(dashboard.subprocess, "Popen", fake_popen)
    result = dashboard.start_backend("my-token")

    assert result == "fake-proc"
    assert captured["args"][-4:] == ["--host", dashboard.BACKEND_HOST, "--port", "3002"]
    assert captured["env"][dashboard.TOKEN_ENV_VAR] == "my-token"
    assert captured["start_new_session"] is True
    assert captured["cwd"] == str(dashboard.repo_root())


def test_start_frontend_runs_npm_dev_in_frontend_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_popen(args: list[str], **kwargs: object) -> str:
        captured["args"] = args
        captured.update(kwargs)
        return "fake-proc"

    monkeypatch.setattr(dashboard.subprocess, "Popen", fake_popen)
    result = dashboard.start_frontend()

    assert result == "fake-proc"
    assert captured["args"] == ["npm", "run", "dev"]
    assert captured["cwd"] == str(dashboard.frontend_dir())
    assert captured["start_new_session"] is True


# --- grafana_available / start_grafana_port_forward ---


def test_grafana_available_true_when_service_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dashboard.kubectl, "get_json", lambda *a, **k: {"kind": "Service"})
    assert dashboard.grafana_available() is True


def test_grafana_available_false_when_service_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_not_found(*a: object, **k: object) -> None:
        raise NexusError(what="services \"kube-prom-stack-grafana\" not found")

    monkeypatch.setattr(dashboard.kubectl, "get_json", raise_not_found)
    assert dashboard.grafana_available() is False


def test_start_grafana_port_forward_returns_none_when_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dashboard, "grafana_available", lambda: False)
    assert dashboard.start_grafana_port_forward() is None


def test_start_grafana_port_forward_launches_kubectl_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dashboard, "grafana_available", lambda: True)
    captured: dict[str, object] = {}

    def fake_popen(args: list[str], **kwargs: object) -> str:
        captured["args"] = args
        captured.update(kwargs)
        return "fake-proc"

    monkeypatch.setattr(dashboard.subprocess, "Popen", fake_popen)
    result = dashboard.start_grafana_port_forward()

    assert result == "fake-proc"
    assert captured["args"] == [
        "kubectl",
        "port-forward",
        "svc/kube-prom-stack-grafana",
        "3000:80",
        "-n",
        "monitoring",
    ]
    assert captured["start_new_session"] is True


# --- wait_for_backend_ready ---


def test_wait_for_backend_ready_returns_on_first_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        dashboard.urllib.request, "urlopen", lambda url, timeout=1: _FakeContextManager()
    )
    dashboard.wait_for_backend_ready(timeout=5)  # must not raise


class _FakeContextManager:
    def __enter__(self) -> _FakeContextManager:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def test_wait_for_backend_ready_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def fake_urlopen(url: str, timeout: int = 1) -> _FakeContextManager:
        calls["n"] += 1
        if calls["n"] < 3:
            raise OSError("connection refused")
        return _FakeContextManager()

    monkeypatch.setattr(dashboard.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(dashboard.time, "sleep", lambda s: None)
    dashboard.wait_for_backend_ready(timeout=5)
    assert calls["n"] == 3


def test_wait_for_backend_ready_raises_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def always_fails(url: str, timeout: int = 1) -> _FakeContextManager:
        raise OSError("connection refused")

    monkeypatch.setattr(dashboard.urllib.request, "urlopen", always_fails)
    monkeypatch.setattr(dashboard.time, "sleep", lambda s: None)
    fake_clock = iter([0, 1, 2, 100])
    monkeypatch.setattr(dashboard.time, "monotonic", lambda: next(fake_clock))
    with pytest.raises(NexusError, match="did not become ready"):
        dashboard.wait_for_backend_ready(timeout=5)


# --- shutdown ---


class _FakeProc:
    def __init__(self, *, alive_for_waits: int = 0) -> None:
        self.pid = 4242
        self._alive_for_waits = alive_for_waits
        self._wait_calls = 0
        self.terminated_signals: list[int] = []

    def poll(self) -> int | None:
        return None  # always "still running" for these tests

    def wait(self, timeout: float | None = None) -> int:
        self._wait_calls += 1
        if self._wait_calls <= self._alive_for_waits:
            raise subprocess.TimeoutExpired(cmd="x", timeout=timeout or 0)
        return 0


def test_shutdown_sends_sigterm_to_process_group(monkeypatch: pytest.MonkeyPatch) -> None:
    killed: list[tuple[int, int]] = []
    monkeypatch.setattr(dashboard.os, "killpg", lambda pid, sig: killed.append((pid, sig)))
    proc = _FakeProc()
    dashboard.shutdown(proc)
    assert killed == [(proc.pid, signal.SIGTERM)]


def test_shutdown_escalates_to_sigkill_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    killed: list[tuple[int, int]] = []
    monkeypatch.setattr(dashboard.os, "killpg", lambda pid, sig: killed.append((pid, sig)))
    proc = _FakeProc(alive_for_waits=1)
    dashboard.shutdown(proc)
    assert killed == [(proc.pid, signal.SIGTERM), (proc.pid, signal.SIGKILL)]


def test_shutdown_skips_already_exited_processes(monkeypatch: pytest.MonkeyPatch) -> None:
    killed: list[tuple[int, int]] = []
    monkeypatch.setattr(dashboard.os, "killpg", lambda pid, sig: killed.append((pid, sig)))

    class _AlreadyExited(_FakeProc):
        def poll(self) -> int | None:
            return 0

    dashboard.shutdown(_AlreadyExited())
    assert killed == []


def test_shutdown_ignores_process_already_gone(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_gone(pid: int, sig: int) -> None:
        raise ProcessLookupError

    monkeypatch.setattr(dashboard.os, "killpg", raise_gone)
    dashboard.shutdown(_FakeProc())  # must not raise
