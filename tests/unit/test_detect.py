"""Unit tests for nexus_cli.core.detect (PRD §7.1 stack detection)."""

from __future__ import annotations

from pathlib import Path

import pytest

from nexus_cli.core import detect
from nexus_cli.core.output import NexusError


def test_detects_node_from_package_json(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("{}")
    result = detect.detect_stack(tmp_path)
    assert result.name == "node"
    assert result.port == 3000
    assert result.health_path == "/health"
    assert result.env[0].name == "NODE_ENV"


def test_detects_flask_from_app_py_and_requirements(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("")
    (tmp_path / "requirements.txt").write_text("flask\n")
    result = detect.detect_stack(tmp_path)
    assert result.name == "flask"
    assert result.port == 5000
    assert result.health_path == "/health"


def test_app_py_without_requirements_is_generic(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("")
    result = detect.detect_stack(tmp_path)
    assert result.name == "generic"


def test_empty_directory_is_generic(tmp_path: Path) -> None:
    result = detect.detect_stack(tmp_path)
    assert result.name == "generic"
    assert result.port is None
    assert result.health_path is None


def test_package_json_takes_precedence_over_flask_signals(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("{}")
    (tmp_path / "app.py").write_text("")
    (tmp_path / "requirements.txt").write_text("")
    result = detect.detect_stack(tmp_path)
    assert result.name == "node"


def test_preset_lookup_by_name() -> None:
    assert detect.preset("flask").port == 5000
    assert detect.preset("node").port == 3000
    assert detect.preset("generic").port is None


def test_preset_unknown_stack_raises_nexus_error() -> None:
    with pytest.raises(NexusError) as exc_info:
        detect.preset("rails")
    assert "node" in exc_info.value.why
    assert "flask" in exc_info.value.why
