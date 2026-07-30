"""Tests for the `nexus init` command (PRD §7.1)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from nexus_cli.main import app

runner = CliRunner()


def test_init_detects_node_and_creates_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "package.json").write_text("{}")
    result = runner.invoke(
        app,
        ["init"],
        input="myrepo/app:latest\nhttps://github.com/user/repo.git\n\n",
    )
    assert result.exit_code == 0, result.stdout
    cfg_path = tmp_path / "nexus.yaml"
    assert cfg_path.exists()
    data = yaml.safe_load(cfg_path.read_text())
    assert data["app"]["port"] == 3000
    assert data["app"]["healthPath"] == "/health"
    assert data["app"]["stack"] == "node"
    assert data["platform"]["branch"] == "main"


def test_init_detects_flask(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "app.py").write_text("")
    (tmp_path / "requirements.txt").write_text("flask\n")
    result = runner.invoke(
        app,
        ["init"],
        input="myrepo/app:latest\nhttps://github.com/user/repo.git\nmain\n",
    )
    assert result.exit_code == 0, result.stdout
    data = yaml.safe_load((tmp_path / "nexus.yaml").read_text())
    assert data["app"]["port"] == 5000
    assert data["app"]["stack"] == "flask"


def test_init_generic_prompts_for_port_and_health(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app,
        ["init"],
        input="8080\n/status\nmyrepo/app:latest\nhttps://github.com/user/repo.git\nmain\n",
    )
    assert result.exit_code == 0, result.stdout
    data = yaml.safe_load((tmp_path / "nexus.yaml").read_text())
    assert data["app"]["port"] == 8080
    assert data["app"]["healthPath"] == "/status"
    assert data["app"].get("stack") is None  # omitted from YAML (exclude_none)


def test_init_generated_config_opts_into_run_as_non_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The schema itself defaults app.security.runAsNonRoot to false (an
    arbitrary existing image may run as root) — but a freshly generated
    config has no such image yet, so `nexus init` opts new apps in. See
    SecurityConfig's docstring in core/config.py.
    """
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app,
        ["init", "--stack", "flask"],
        input="myrepo/app:latest\nhttps://github.com/user/repo.git\nmain\n",
    )
    assert result.exit_code == 0, result.stdout
    data = yaml.safe_load((tmp_path / "nexus.yaml").read_text())
    assert data["app"]["security"]["runAsNonRoot"] is True


def test_init_stack_flag_forces_preset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "package.json").write_text("{}")  # would auto-detect node
    result = runner.invoke(
        app,
        ["init", "--stack", "flask"],
        input="myrepo/app:latest\nhttps://github.com/user/repo.git\nmain\n",
    )
    assert result.exit_code == 0, result.stdout
    data = yaml.safe_load((tmp_path / "nexus.yaml").read_text())
    assert data["app"]["port"] == 5000
    assert data["app"]["stack"] == "flask"


def test_init_unknown_stack_flag_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init", "--stack", "rails"])
    assert result.exit_code != 0
    assert not (tmp_path / "nexus.yaml").exists()


def test_init_does_not_overwrite_without_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    existing = tmp_path / "nexus.yaml"
    existing.write_text("app: {}\n")
    result = runner.invoke(app, ["init"], input="n\n")
    assert result.exit_code != 0
    assert existing.read_text() == "app: {}\n"


def test_init_overwrites_when_confirmed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    existing = tmp_path / "nexus.yaml"
    existing.write_text("app: {}\n")
    (tmp_path / "package.json").write_text("{}")
    result = runner.invoke(
        app,
        ["init"],
        input="y\nmyrepo/app:latest\nhttps://github.com/user/repo.git\nmain\n",
    )
    assert result.exit_code == 0, result.stdout
    data = yaml.safe_load(existing.read_text())
    assert data["app"]["image"] == "myrepo/app:latest"


def test_init_invalid_image_reports_error_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "package.json").write_text("{}")
    result = runner.invoke(
        app,
        ["init"],
        input="myrepo/app\nhttps://github.com/user/repo.git\nmain\n",  # no tag -> invalid
    )
    assert result.exit_code != 0
    assert not (tmp_path / "nexus.yaml").exists()


def test_init_default_app_name_is_sanitized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_dir = tmp_path / "My_Weird Project!!"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)
    result = runner.invoke(
        app,
        ["init"],
        input="8080\n/status\nmyrepo/app:latest\nhttps://github.com/user/repo.git\nmain\n",
    )
    assert result.exit_code == 0, result.stdout
    data = yaml.safe_load((project_dir / "nexus.yaml").read_text())
    assert data["app"]["name"] == "my-weird-project"
