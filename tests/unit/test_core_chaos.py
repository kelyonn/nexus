"""Unit tests for nexus_cli.core.chaos (mocked kubectl; no live cluster).

The webhook-retry tests here are built against the exact error text a live
Chaos Mesh install produced (see the module docstring in core/chaos.py).
"""

from __future__ import annotations

import pytest
import yaml

from nexus_cli.core import chaos
from nexus_cli.core.output import NexusError

# --- with_webhook_retry ---


def test_with_webhook_retry_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def flaky() -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise NexusError(what="apply failed", why='failed calling webhook "vauth.kb.io"')

    monkeypatch.setattr(chaos.time, "sleep", lambda s: None)
    fake_clock = iter([0, 1, 2])  # deadline calc, then one loop retry
    monkeypatch.setattr(chaos.time, "monotonic", lambda: next(fake_clock))

    chaos.with_webhook_retry(flaky)
    assert calls["n"] == 2


def test_with_webhook_retry_gives_up_after_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    def always_fails() -> None:
        raise NexusError(what="apply failed", why='failed calling webhook "vauth.kb.io"')

    monkeypatch.setattr(chaos.time, "sleep", lambda s: None)
    fake_clock = iter([0, 100])  # deadline=0+20=20, first retry-check: 100 >= 20 -> give up
    monkeypatch.setattr(chaos.time, "monotonic", lambda: next(fake_clock))

    with pytest.raises(NexusError, match="failed calling webhook"):
        chaos.with_webhook_retry(always_fails)


def test_with_webhook_retry_does_not_retry_other_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def fails_differently() -> None:
        calls["n"] += 1
        raise NexusError(what="apply failed", why="some other kubectl error")

    with pytest.raises(NexusError, match="some other kubectl error"):
        chaos.with_webhook_retry(fails_differently)
    assert calls["n"] == 1


# --- validate_action ---


def test_validate_action_accepts_supported_actions() -> None:
    for action in ("pod-kill", "pod-failure", "container-kill"):
        chaos.validate_action(action)  # must not raise


def test_validate_action_rejects_unknown_with_fix() -> None:
    with pytest.raises(NexusError) as exc_info:
        chaos.validate_action("delete-cluster")
    assert "delete-cluster" in exc_info.value.what
    assert "pod-kill" in (exc_info.value.why or "")
    assert exc_info.value.fix


# --- build_experiment ---


def test_build_experiment_targets_one_pod_by_default() -> None:
    manifest = chaos.build_experiment("my-app", action="pod-kill", kill_all=False, run_name="r1")
    assert manifest["kind"] == "PodChaos"
    assert manifest["metadata"]["name"] == "r1"
    assert manifest["metadata"]["namespace"] == chaos.NAMESPACE
    assert manifest["metadata"]["labels"]["managed-by"] == "nexus"
    assert manifest["spec"]["mode"] == "one"
    assert manifest["spec"]["action"] == "pod-kill"
    assert manifest["spec"]["selector"]["namespaces"] == ["my-app"]
    assert manifest["spec"]["selector"]["labelSelectors"] == {"app": "my-app"}


def test_build_experiment_kill_all_uses_all_mode() -> None:
    manifest = chaos.build_experiment("my-app", action="pod-kill", kill_all=True, run_name="r1")
    assert manifest["spec"]["mode"] == "all"


# --- run_experiment ---


def test_run_experiment_applies_manifest_and_returns_run_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}
    monkeypatch.setattr(
        chaos.kubectl, "apply_manifest", lambda text: captured.setdefault("text", text)
    )

    run_name = chaos.run_experiment("my-app", action="container-kill", kill_all=False)

    assert run_name.startswith("my-app-chaos-")
    applied = yaml.safe_load(captured["text"])
    assert applied["metadata"]["name"] == run_name
    assert applied["spec"]["action"] == "container-kill"


def test_run_experiment_names_are_unique_per_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chaos.kubectl, "apply_manifest", lambda text: None)
    first = chaos.run_experiment("my-app")
    second = chaos.run_experiment("my-app")
    assert first != second


def test_run_experiment_rejects_bad_action_before_touching_cluster(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(text: str) -> None:
        raise AssertionError("must not apply anything for an invalid action")

    monkeypatch.setattr(chaos.kubectl, "apply_manifest", fail)
    with pytest.raises(NexusError, match="Unknown chaos action"):
        chaos.run_experiment("my-app", action="nope")


# --- pods, schedule helpers ---


def test_pod_names_extracts_names(monkeypatch: pytest.MonkeyPatch) -> None:
    doc = {"items": [{"metadata": {"name": "a"}}, {"metadata": {"name": "b"}}]}
    monkeypatch.setattr(chaos.kubectl, "get_json", lambda *a, **k: doc)
    assert chaos.pod_names("my-app") == {"a", "b"}


def test_list_pod_items_empty_when_no_pods(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chaos.kubectl, "get_json", lambda *a, **k: {})
    assert chaos.list_pod_items("my-app") == []


def test_schedule_name_is_derived_from_app() -> None:
    assert chaos.schedule_name("my-app") == "my-app-chaos-schedule"


def test_patch_pause_annotation_sets_true_when_pausing(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, list[str]] = {}
    monkeypatch.setattr(chaos.kubectl, "run", lambda args, **k: captured.setdefault("args", args))
    chaos.patch_pause_annotation("my-app-chaos-schedule", paused=True)
    assert captured["args"][0] == "patch"
    assert f'"{chaos.PAUSE_ANNOTATION}": "true"' in captured["args"][-1]


def test_patch_pause_annotation_clears_to_null_when_resuming(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, list[str]] = {}
    monkeypatch.setattr(chaos.kubectl, "run", lambda args, **k: captured.setdefault("args", args))
    chaos.patch_pause_annotation("my-app-chaos-schedule", paused=False)
    # A null value removes the annotation rather than setting it to "false".
    assert f'"{chaos.PAUSE_ANNOTATION}": null' in captured["args"][-1]


def test_is_schedule_paused_reads_annotation(monkeypatch: pytest.MonkeyPatch) -> None:
    doc = {"metadata": {"annotations": {chaos.PAUSE_ANNOTATION: "true"}}}
    monkeypatch.setattr(chaos.kubectl, "get_json", lambda *a, **k: doc)
    assert chaos.is_schedule_paused("my-app-chaos-schedule") is True


def test_is_schedule_paused_false_when_annotation_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chaos.kubectl, "get_json", lambda *a, **k: {"metadata": {}})
    assert chaos.is_schedule_paused("my-app-chaos-schedule") is False
