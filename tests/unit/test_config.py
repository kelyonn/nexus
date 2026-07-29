"""Unit tests for nexus_cli.core.config (PRD §9 schema + validation rules)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from nexus_cli.core import config
from nexus_cli.core.output import NexusError

VALID_APP = {
    "name": "my-webapp",
    "image": "myrepo/app:latest",
    "port": 3000,
    "healthPath": "/health",
}
VALID_PLATFORM = {
    "repoURL": "https://github.com/user/repo.git",
    "branch": "main",
}


def _write(tmp_path: Path, app: dict, platform: dict) -> Path:
    p = tmp_path / "nexus.yaml"
    p.write_text(yaml.safe_dump({"app": app, "platform": platform}))
    return p


# --- happy path ---


def test_minimal_valid_config_loads_with_defaults(tmp_path: Path) -> None:
    p = _write(tmp_path, VALID_APP, VALID_PLATFORM)
    cfg = config.load(p)
    assert cfg.app.name == "my-webapp"
    assert cfg.app.replicas == 2  # default
    assert cfg.app.stack is None  # auto-detect
    assert cfg.app.resources.requests.cpu == "100m"
    assert cfg.app.resources.requests.memory == "128Mi"
    assert cfg.app.resources.limits.cpu == "500m"
    assert cfg.app.resources.limits.memory == "512Mi"
    assert cfg.platform.monitoring is True
    assert cfg.platform.chaos is False
    assert cfg.platform.chaosSchedule == "*/30 * * * *"
    assert cfg.app.imagePullPolicy == "Always"  # default


def test_full_valid_config_loads(tmp_path: Path) -> None:
    app = {
        **VALID_APP,
        "stack": "node",
        "replicas": 4,
        "env": [{"name": "NODE_ENV", "value": "production"}],
        "resources": {
            "requests": {"cpu": "200m", "memory": "256Mi"},
            "limits": {"cpu": "1", "memory": "1Gi"},
        },
    }
    platform = {**VALID_PLATFORM, "monitoring": False, "chaos": True, "chaosSchedule": "0 * * * *"}
    p = _write(tmp_path, app, platform)
    cfg = config.load(p)
    assert cfg.app.replicas == 4
    assert cfg.app.env[0].name == "NODE_ENV"
    assert cfg.platform.chaos is True


def test_ssh_repo_url_accepted(tmp_path: Path) -> None:
    platform = {**VALID_PLATFORM, "repoURL": "git@github.com:user/repo.git"}
    p = _write(tmp_path, VALID_APP, platform)
    cfg = config.load(p)
    assert cfg.platform.repoURL.startswith("git@")


def test_to_yaml_roundtrips(tmp_path: Path) -> None:
    p = _write(tmp_path, VALID_APP, VALID_PLATFORM)
    cfg = config.load(p)
    dumped = cfg.to_yaml()
    reloaded = yaml.safe_load(dumped)
    assert reloaded["app"]["name"] == "my-webapp"


# --- missing file / malformed ---


def test_missing_file_raises_nexus_error(tmp_path: Path) -> None:
    with pytest.raises(NexusError) as exc_info:
        config.load(tmp_path / "does-not-exist.yaml")
    assert "nexus init" in exc_info.value.fix


def test_empty_file_raises_nexus_error(tmp_path: Path) -> None:
    p = tmp_path / "nexus.yaml"
    p.write_text("")
    with pytest.raises(NexusError):
        config.load(p)


def test_malformed_yaml_raises_nexus_error(tmp_path: Path) -> None:
    p = tmp_path / "nexus.yaml"
    p.write_text("app: [unclosed")
    with pytest.raises(NexusError):
        config.load(p)


# --- required fields ---


@pytest.mark.parametrize("missing", ["name", "image", "port", "healthPath"])
def test_missing_required_app_field_raises(tmp_path: Path, missing: str) -> None:
    app = {k: v for k, v in VALID_APP.items() if k != missing}
    p = _write(tmp_path, app, VALID_PLATFORM)
    with pytest.raises(NexusError):
        config.load(p)


@pytest.mark.parametrize("missing", ["repoURL", "branch"])
def test_missing_required_platform_field_raises(tmp_path: Path, missing: str) -> None:
    platform = {k: v for k, v in VALID_PLATFORM.items() if k != missing}
    p = _write(tmp_path, VALID_APP, platform)
    with pytest.raises(NexusError):
        config.load(p)


# --- one invalid-input test per §9 validation rule ---


def test_invalid_name_bad_chars(tmp_path: Path) -> None:
    app = {**VALID_APP, "name": "My_Web_App"}
    p = _write(tmp_path, app, VALID_PLATFORM)
    with pytest.raises(NexusError) as exc_info:
        config.load(p)
    assert "name" in exc_info.value.why


def test_invalid_name_too_long(tmp_path: Path) -> None:
    app = {**VALID_APP, "name": "a" * 41}
    p = _write(tmp_path, app, VALID_PLATFORM)
    with pytest.raises(NexusError):
        config.load(p)


def test_invalid_image_no_tag(tmp_path: Path) -> None:
    app = {**VALID_APP, "image": "myrepo/app"}
    p = _write(tmp_path, app, VALID_PLATFORM)
    with pytest.raises(NexusError) as exc_info:
        config.load(p)
    assert "image" in exc_info.value.why


def test_invalid_port_zero(tmp_path: Path) -> None:
    app = {**VALID_APP, "port": 0}
    p = _write(tmp_path, app, VALID_PLATFORM)
    with pytest.raises(NexusError):
        config.load(p)


def test_invalid_port_too_high(tmp_path: Path) -> None:
    app = {**VALID_APP, "port": 70000}
    p = _write(tmp_path, app, VALID_PLATFORM)
    with pytest.raises(NexusError):
        config.load(p)


def test_invalid_health_path_missing_leading_slash(tmp_path: Path) -> None:
    app = {**VALID_APP, "healthPath": "health"}
    p = _write(tmp_path, app, VALID_PLATFORM)
    with pytest.raises(NexusError) as exc_info:
        config.load(p)
    assert "healthPath" in exc_info.value.why


def test_invalid_stack_value(tmp_path: Path) -> None:
    app = {**VALID_APP, "stack": "rails"}
    p = _write(tmp_path, app, VALID_PLATFORM)
    with pytest.raises(NexusError):
        config.load(p)


def test_valid_image_pull_policy_if_not_present(tmp_path: Path) -> None:
    app = {**VALID_APP, "imagePullPolicy": "IfNotPresent"}
    p = _write(tmp_path, app, VALID_PLATFORM)
    cfg = config.load(p)
    assert cfg.app.imagePullPolicy == "IfNotPresent"


def test_invalid_image_pull_policy(tmp_path: Path) -> None:
    app = {**VALID_APP, "imagePullPolicy": "Sometimes"}
    p = _write(tmp_path, app, VALID_PLATFORM)
    with pytest.raises(NexusError):
        config.load(p)


def test_invalid_replicas_zero(tmp_path: Path) -> None:
    app = {**VALID_APP, "replicas": 0}
    p = _write(tmp_path, app, VALID_PLATFORM)
    with pytest.raises(NexusError):
        config.load(p)


def test_invalid_replicas_too_high(tmp_path: Path) -> None:
    app = {**VALID_APP, "replicas": 21}
    p = _write(tmp_path, app, VALID_PLATFORM)
    with pytest.raises(NexusError):
        config.load(p)


def test_invalid_requests_cpu(tmp_path: Path) -> None:
    app = {**VALID_APP, "resources": {"requests": {"cpu": "lots", "memory": "128Mi"}}}
    p = _write(tmp_path, app, VALID_PLATFORM)
    with pytest.raises(NexusError) as exc_info:
        config.load(p)
    assert "cpu" in exc_info.value.why


def test_invalid_limits_memory(tmp_path: Path) -> None:
    app = {**VALID_APP, "resources": {"limits": {"cpu": "500m", "memory": "huge"}}}
    p = _write(tmp_path, app, VALID_PLATFORM)
    with pytest.raises(NexusError) as exc_info:
        config.load(p)
    assert "memory" in exc_info.value.why


def test_invalid_repo_url(tmp_path: Path) -> None:
    platform = {**VALID_PLATFORM, "repoURL": "not-a-url"}
    p = _write(tmp_path, VALID_APP, platform)
    with pytest.raises(NexusError) as exc_info:
        config.load(p)
    assert "repoURL" in exc_info.value.why


def test_invalid_chaos_schedule(tmp_path: Path) -> None:
    platform = {**VALID_PLATFORM, "chaosSchedule": "not a cron"}
    p = _write(tmp_path, VALID_APP, platform)
    with pytest.raises(NexusError) as exc_info:
        config.load(p)
    assert "chaosSchedule" in exc_info.value.why


def test_unknown_field_rejected(tmp_path: Path) -> None:
    app = {**VALID_APP, "unexpectedField": "nope"}
    p = _write(tmp_path, app, VALID_PLATFORM)
    with pytest.raises(NexusError):
        config.load(p)
