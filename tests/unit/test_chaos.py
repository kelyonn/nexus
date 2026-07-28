"""Tests for `nexus chaos run` and `nexus chaos schedule` (PRD §7.6, §7.7)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from nexus_cli.commands import chaos as chaos_module
from nexus_cli.core import config as nexus_config
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


def _pod(name: str, phase: str) -> dict:
    return {"metadata": {"name": name}, "status": {"phase": phase}}


def _setup_common(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, chaos_mesh: bool = True, app_ns: bool = True
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    monkeypatch.setattr(preflight, "ensure_cluster_ready", lambda **k: None)

    def namespace_exists(name: str) -> bool:
        if name == chaos_module.CHAOS_NAMESPACE:
            return chaos_mesh
        return app_ns

    monkeypatch.setattr(chaos_module.kubectl, "namespace_exists", namespace_exists)


# --- nexus chaos run ---


def test_chaos_run_invalid_action(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["chaos", "run", "--action", "bogus"])
    assert result.exit_code != 0
    assert "Unknown chaos action" in result.output


def test_chaos_run_chaos_mesh_not_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_common(tmp_path, monkeypatch, chaos_mesh=False)
    result = runner.invoke(app, ["chaos", "run"])
    assert result.exit_code != 0
    assert "Chaos Mesh is not installed" in result.output


def test_chaos_run_app_namespace_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_common(tmp_path, monkeypatch, app_ns=False)
    result = runner.invoke(app, ["chaos", "run"])
    assert result.exit_code != 0
    assert "not found" in result.output


def test_chaos_run_applies_manifest_and_reports_active(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_common(tmp_path, monkeypatch)
    captured: dict[str, str] = {}
    monkeypatch.setattr(
        chaos_module.kubectl, "apply_manifest", lambda text: captured.setdefault("text", text)
    )
    # Immediate "recovery": before/after pod sets identical minus nothing lost,
    # so the recovery poll loop should never trigger (deadline already passed).
    monkeypatch.setattr(chaos_module.kubectl, "get_json", lambda *a, **k: {"items": []})
    # First value is consumed by _with_webhook_retry's own deadline calc (apply
    # succeeds immediately, no retry loop); the rest drive _report_recovery.
    fake_clock = iter([0, 0, 100])  # deadline=0+60=60, first while-check: 100 < 60 -> False
    monkeypatch.setattr(chaos_module.time, "monotonic", lambda: next(fake_clock))

    result = runner.invoke(app, ["chaos", "run"])
    assert result.exit_code == 0, result.output
    manifest = yaml.safe_load(captured["text"])
    assert manifest["kind"] == "PodChaos"
    assert manifest["spec"]["action"] == "pod-kill"
    assert manifest["spec"]["mode"] == "one"
    assert manifest["spec"]["selector"]["namespaces"] == ["my-app"]
    assert "is active" in result.output


def test_chaos_run_kill_all_sets_mode_all(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_common(tmp_path, monkeypatch)
    captured: dict[str, str] = {}
    monkeypatch.setattr(
        chaos_module.kubectl, "apply_manifest", lambda text: captured.setdefault("text", text)
    )
    monkeypatch.setattr(chaos_module.kubectl, "get_json", lambda *a, **k: {"items": []})
    fake_clock = iter([0, 0, 100])  # first value consumed by _with_webhook_retry
    monkeypatch.setattr(chaos_module.time, "monotonic", lambda: next(fake_clock))

    result = runner.invoke(app, ["chaos", "run", "--kill-all", "--action", "pod-failure"])
    assert result.exit_code == 0, result.output
    manifest = yaml.safe_load(captured["text"])
    assert manifest["spec"]["mode"] == "all"
    assert manifest["spec"]["action"] == "pod-failure"


def test_report_recovery_reports_kill_then_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = {"pod-a", "pod-b"}
    # Poll 1: pod-a gone, pod-b still Running, replacement not up yet (count < expected).
    # Poll 2: pod-a's replacement is up, both pods Running -> recovered.
    responses = iter(
        [
            [_pod("pod-b", "Running")],
            [_pod("pod-b", "Running"), _pod("pod-a-new", "Running")],
        ]
    )
    monkeypatch.setattr(
        chaos_module.kubectl, "get_json", lambda *a, **k: {"items": next(responses)}
    )
    monkeypatch.setattr(chaos_module.time, "sleep", lambda s: None)
    fake_clock = iter([0, 1, 2])
    monkeypatch.setattr(chaos_module.time, "monotonic", lambda: next(fake_clock))

    chaos_module._report_recovery("my-app", before, timeout=60, poll_interval=0)


def test_report_recovery_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    before = {"pod-a", "pod-b"}
    # Pod never comes back — count stays below expected forever.
    monkeypatch.setattr(
        chaos_module.kubectl,
        "get_json",
        lambda *a, **k: {"items": [_pod("pod-b", "Running")]},
    )
    monkeypatch.setattr(chaos_module.time, "sleep", lambda s: None)
    fake_clock = iter([0, 1, 2, 100])
    monkeypatch.setattr(chaos_module.time, "monotonic", lambda: next(fake_clock))

    chaos_module._report_recovery("my-app", before, timeout=60, poll_interval=0)


# --- nexus chaos schedule enable/disable ---


def test_schedule_enable_applies_and_reports_active(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_common(tmp_path, monkeypatch)
    monkeypatch.setattr(chaos_module.render, "render_template", lambda name, cfg: "kind: Schedule")
    applied: dict[str, str] = {}
    monkeypatch.setattr(
        chaos_module.kubectl, "apply_manifest", lambda text: applied.setdefault("text", text)
    )
    patch_calls: list[list[str]] = []
    monkeypatch.setattr(
        chaos_module.kubectl, "run", lambda args, **k: patch_calls.append(args)
    )
    monkeypatch.setattr(
        chaos_module.kubectl,
        "get_json",
        lambda *a, **k: {"metadata": {"annotations": {}}},
    )

    result = runner.invoke(app, ["chaos", "schedule", "enable"])
    assert result.exit_code == 0, result.output
    assert applied["text"] == "kind: Schedule"
    assert any("patch" in c for c in patch_calls)
    assert "enabled" in result.output
    assert "Active" in result.output


def test_schedule_disable_pauses_and_reports_suspended(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_common(tmp_path, monkeypatch)
    get_json_calls: list[dict] = []

    def get_json(resource: str, **kwargs: object) -> dict:
        get_json_calls.append(kwargs)
        if len(get_json_calls) == 1:
            return {"metadata": {"name": "my-app-chaos-schedule"}}
        return {
            "metadata": {
                "annotations": {chaos_module._PAUSE_ANNOTATION: "true"},
            }
        }

    monkeypatch.setattr(chaos_module.kubectl, "get_json", get_json)
    patch_calls: list[list[str]] = []
    monkeypatch.setattr(chaos_module.kubectl, "run", lambda args, **k: patch_calls.append(args))

    result = runner.invoke(app, ["chaos", "schedule", "disable"])
    assert result.exit_code == 0, result.output
    assert any("patch" in c for c in patch_calls)
    assert "suspended" in result.output
    assert "Suspended" in result.output


def test_schedule_disable_not_found_gives_friendly_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_common(tmp_path, monkeypatch)

    def raise_not_found(*a: object, **k: object) -> None:
        raise NexusError(what="schedules.chaos-mesh.org \"my-app-chaos-schedule\" not found")

    monkeypatch.setattr(chaos_module.kubectl, "get_json", raise_not_found)

    result = runner.invoke(app, ["chaos", "schedule", "disable"])
    assert result.exit_code != 0
    assert "No chaos schedule found" in result.output


def test_schedule_enable_requires_chaos_mesh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_common(tmp_path, monkeypatch, chaos_mesh=False)
    result = runner.invoke(app, ["chaos", "schedule", "enable"])
    assert result.exit_code != 0
    assert "Chaos Mesh is not installed" in result.output


# --- _with_webhook_retry ---


def test_with_webhook_retry_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def flaky() -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise NexusError(what="apply failed", why='failed calling webhook "vauth.kb.io"')

    monkeypatch.setattr(chaos_module.time, "sleep", lambda s: None)
    fake_clock = iter([0, 1, 2])  # deadline calc, then one loop retry
    monkeypatch.setattr(chaos_module.time, "monotonic", lambda: next(fake_clock))

    chaos_module._with_webhook_retry(flaky)
    assert calls["n"] == 2


def test_with_webhook_retry_gives_up_after_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    def always_fails() -> None:
        raise NexusError(what="apply failed", why='failed calling webhook "vauth.kb.io"')

    monkeypatch.setattr(chaos_module.time, "sleep", lambda s: None)
    fake_clock = iter([0, 100])  # deadline=0+20=20, first retry-check: 100 >= 20 -> give up
    monkeypatch.setattr(chaos_module.time, "monotonic", lambda: next(fake_clock))

    with pytest.raises(NexusError, match="failed calling webhook"):
        chaos_module._with_webhook_retry(always_fails)


def test_with_webhook_retry_does_not_retry_other_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def fails_differently() -> None:
        calls["n"] += 1
        raise NexusError(what="apply failed", why="some other kubectl error")

    with pytest.raises(NexusError, match="some other kubectl error"):
        chaos_module._with_webhook_retry(fails_differently)
    assert calls["n"] == 1


def test_chaos_config_loaded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Sanity check `_ensure_ready` actually parses the app name it reports."""
    _setup_common(tmp_path, monkeypatch)
    cfg = chaos_module._ensure_ready(str(tmp_path / "nexus.yaml"))
    assert isinstance(cfg, nexus_config.NexusConfig)
    assert cfg.app.name == "my-app"
