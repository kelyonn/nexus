"""Tests for the `nexus open` command."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from nexus_cli.commands import open as open_module
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


class _FakeProc:
    def __init__(self) -> None:
        self.waited = False
        self.wait_raises: BaseException | None = None

    def wait(self) -> int:
        self.waited = True
        if self.wait_raises is not None:
            raise self.wait_raises
        return 0


def test_open_preflight_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)

    def fail(**k: object) -> None:
        raise NexusError(what="cluster not reachable")

    monkeypatch.setattr(preflight, "ensure_cluster_ready", fail)
    result = runner.invoke(app, ["open"])
    assert result.exit_code != 0
    assert "cluster not reachable" in result.output


def test_open_reports_missing_service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    monkeypatch.setattr(preflight, "ensure_cluster_ready", lambda **k: None)
    monkeypatch.setattr(open_module.core_dashboard, "start_port_forward", lambda *a: None)

    result = runner.invoke(app, ["open"])
    assert result.exit_code != 0
    assert "Service 'my-app' not found" in result.output
    assert "nexus deploy" in result.output


def test_open_reports_port_forward_never_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    monkeypatch.setattr(preflight, "ensure_cluster_ready", lambda **k: None)
    proc = _FakeProc()
    monkeypatch.setattr(open_module.core_dashboard, "start_port_forward", lambda *a: proc)
    monkeypatch.setattr(open_module, "_wait_for_port", lambda port, timeout: False)
    shutdown_calls: list[object] = []
    monkeypatch.setattr(
        open_module.core_dashboard, "shutdown", lambda *procs: shutdown_calls.append(procs)
    )

    result = runner.invoke(app, ["open"])
    assert result.exit_code != 0
    assert "did not become ready" in result.output
    assert shutdown_calls == [(proc,)]


def test_open_happy_path_opens_browser_and_shuts_down_on_ctrl_c(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    monkeypatch.setattr(preflight, "ensure_cluster_ready", lambda **k: None)
    proc = _FakeProc()
    proc.wait_raises = KeyboardInterrupt
    monkeypatch.setattr(open_module.core_dashboard, "start_port_forward", lambda *a: proc)
    monkeypatch.setattr(open_module, "_wait_for_port", lambda port, timeout: True)
    opened: dict[str, str] = {}
    monkeypatch.setattr(open_module.webbrowser, "open", lambda url: opened.setdefault("url", url))
    shutdown_calls: list[object] = []
    monkeypatch.setattr(
        open_module.core_dashboard, "shutdown", lambda *procs: shutdown_calls.append(procs)
    )

    result = runner.invoke(app, ["open"])
    assert result.exit_code == 0, result.output
    assert opened["url"] == "http://127.0.0.1:18080"
    assert "Opening http://127.0.0.1:18080" in result.output
    assert proc.waited is True
    assert shutdown_calls == [(proc,)]
