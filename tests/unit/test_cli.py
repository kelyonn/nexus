"""Smoke tests for the CLI entry point."""

from __future__ import annotations

from typer.testing import CliRunner

from nexus_cli import __version__
from nexus_cli.main import app

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Nexus" in result.stdout


def test_no_args_shows_help() -> None:
    result = runner.invoke(app, [])
    # no_args_is_help renders help; Typer exits 0 or 2 depending on version.
    assert result.exit_code in (0, 2)
    assert "Usage" in result.stdout or "Bring your app" in result.stdout
