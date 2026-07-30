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


def test_metrics_path_unset_by_default(tmp_path: Path) -> None:
    p = _write(tmp_path, VALID_APP, VALID_PLATFORM)
    cfg = config.load(p)
    assert cfg.app.metricsPath is None
    assert cfg.app.metricsPort is None
    assert cfg.app.effective_metrics_port == cfg.app.port


def test_metrics_path_and_port_set(tmp_path: Path) -> None:
    app = {**VALID_APP, "metricsPath": "/metrics", "metricsPort": 9100}
    p = _write(tmp_path, app, VALID_PLATFORM)
    cfg = config.load(p)
    assert cfg.app.metricsPath == "/metrics"
    assert cfg.app.effective_metrics_port == 9100


def test_metrics_path_defaults_port_to_app_port(tmp_path: Path) -> None:
    app = {**VALID_APP, "metricsPath": "/metrics"}
    p = _write(tmp_path, app, VALID_PLATFORM)
    cfg = config.load(p)
    assert cfg.app.effective_metrics_port == cfg.app.port


def test_invalid_metrics_path_missing_leading_slash(tmp_path: Path) -> None:
    app = {**VALID_APP, "metricsPath": "metrics"}
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


# --- app.registry (imagePullSecrets automation) ---

VALID_REGISTRY = {
    "server": "ghcr.io",
    "usernameEnv": "REGISTRY_USERNAME",
    "passwordEnv": "REGISTRY_PASSWORD",
}


def test_registry_unset_by_default(tmp_path: Path) -> None:
    p = _write(tmp_path, VALID_APP, VALID_PLATFORM)
    cfg = config.load(p)
    assert cfg.app.registry is None


def test_registry_valid_config_loads(tmp_path: Path) -> None:
    app = {**VALID_APP, "registry": VALID_REGISTRY}
    p = _write(tmp_path, app, VALID_PLATFORM)
    cfg = config.load(p)
    assert cfg.app.registry is not None
    assert cfg.app.registry.server == "ghcr.io"
    assert cfg.app.registry.usernameEnv == "REGISTRY_USERNAME"
    assert cfg.app.registry.passwordEnv == "REGISTRY_PASSWORD"


@pytest.mark.parametrize("field", ["server", "usernameEnv", "passwordEnv"])
def test_registry_empty_field_rejected(tmp_path: Path, field: str) -> None:
    app = {**VALID_APP, "registry": {**VALID_REGISTRY, field: ""}}
    p = _write(tmp_path, app, VALID_PLATFORM)
    with pytest.raises(NexusError) as exc_info:
        config.load(p)
    assert field in exc_info.value.why


def test_registry_unknown_field_rejected(tmp_path: Path) -> None:
    app = {**VALID_APP, "registry": {**VALID_REGISTRY, "password": "shouldnt-exist"}}
    p = _write(tmp_path, app, VALID_PLATFORM)
    with pytest.raises(NexusError):
        config.load(p)


def test_registry_secret_name_derived_from_app_name(tmp_path: Path) -> None:
    p = _write(tmp_path, VALID_APP, VALID_PLATFORM)
    cfg = config.load(p)
    assert cfg.app.registry_secret_name == f"{cfg.app.name}-registry"


# --- injection-hardening validators (see docs/INTERVIEW-BRIEF.md) ---
#
# EnvVar.name, PlatformConfig.branch, and the healthPath/metricsPath charset
# were unvalidated (or under-validated) before this fix, and every one of
# them lands unquoted in a generated manifest. These payloads are the exact
# ones verified (by rendering the templates in-process) to restructure the
# generated Deployment or ArgoCD Application before the fix landed. This
# suite proves they're now rejected at the single config.load() choke point,
# before they ever reach a template.

_HOSTILE_BRANCH = (
    "main\n    path: ../../etc\n  syncPolicy:\n    automated:\n      prune: false\n  # "
)
_HOSTILE_ENV_NAME = (
    'X\n          value: "y"\n        securityContext:\n          privileged: true\n      # '
)


def test_invalid_env_name_rejected(tmp_path: Path) -> None:
    app = {**VALID_APP, "env": [{"name": _HOSTILE_ENV_NAME, "value": "v"}]}
    p = _write(tmp_path, app, VALID_PLATFORM)
    with pytest.raises(NexusError) as exc_info:
        config.load(p)
    assert "env" in exc_info.value.why


@pytest.mark.parametrize("name", ["OK", "_OK", "OK.NAME", "OK-NAME", "OK_1"])
def test_valid_env_names_accepted(tmp_path: Path, name: str) -> None:
    app = {**VALID_APP, "env": [{"name": name, "value": "v"}]}
    p = _write(tmp_path, app, VALID_PLATFORM)
    cfg = config.load(p)
    assert cfg.app.env[0].name == name


def test_env_value_stays_free_text(tmp_path: Path) -> None:
    """EnvVar.value is deliberately NOT validated — users need to put
    arbitrary strings there. Safety for this field comes from `| tojson`
    escaping at the template layer (test_render.py), not from rejecting it
    here.
    """
    hostile_value = 'x"\n        securityContext:\n          privileged: true'
    app = {**VALID_APP, "env": [{"name": "OK", "value": hostile_value}]}
    p = _write(tmp_path, app, VALID_PLATFORM)
    cfg = config.load(p)
    assert cfg.app.env[0].value == hostile_value


def test_invalid_branch_injection_payload_rejected(tmp_path: Path) -> None:
    platform = {**VALID_PLATFORM, "branch": _HOSTILE_BRANCH}
    p = _write(tmp_path, VALID_APP, platform)
    with pytest.raises(NexusError) as exc_info:
        config.load(p)
    assert "branch" in exc_info.value.why


@pytest.mark.parametrize(
    "branch",
    [
        "main",
        "cli-platform",
        "feature/foo",
        "release-1.0",
        "-leading-hyphen",  # rejected: leading '-'
        "trailing/",  # rejected: trailing '/'
        "has..dotdot",  # rejected: '..'
        "ends.lock",  # rejected: trailing '.lock'
        "has space",  # rejected: not in the allowed charset
        'has"quote',  # rejected: not in the allowed charset
    ],
)
def test_branch_validation(tmp_path: Path, branch: str) -> None:
    platform = {**VALID_PLATFORM, "branch": branch}
    p = _write(tmp_path, VALID_APP, platform)
    if branch in ("main", "cli-platform", "feature/foo", "release-1.0"):
        cfg = config.load(p)
        assert cfg.platform.branch == branch
    else:
        with pytest.raises(NexusError) as exc_info:
            config.load(p)
        assert "branch" in exc_info.value.why


@pytest.mark.parametrize(
    "path",
    ['/health"path', "/health path", "/health\npath"],
)
def test_invalid_health_path_hostile_chars_rejected(tmp_path: Path, path: str) -> None:
    app = {**VALID_APP, "healthPath": path}
    p = _write(tmp_path, app, VALID_PLATFORM)
    with pytest.raises(NexusError) as exc_info:
        config.load(p)
    assert "healthPath" in exc_info.value.why


@pytest.mark.parametrize(
    "path",
    ['/metrics"path', "/metrics path", "/metrics\npath"],
)
def test_invalid_metrics_path_hostile_chars_rejected(tmp_path: Path, path: str) -> None:
    app = {**VALID_APP, "metricsPath": path}
    p = _write(tmp_path, app, VALID_PLATFORM)
    with pytest.raises(NexusError) as exc_info:
        config.load(p)
    assert "metricsPath" in exc_info.value.why


# --- app.secrets (real app secrets, as opposed to app.env's free text) ---


def test_secrets_unset_by_default(tmp_path: Path) -> None:
    p = _write(tmp_path, VALID_APP, VALID_PLATFORM)
    cfg = config.load(p)
    assert cfg.app.secrets == []


def test_secrets_valid_config_loads(tmp_path: Path) -> None:
    app = {
        **VALID_APP,
        "secrets": [{"name": "DB_PASSWORD", "valueEnv": "APP_DB_PASSWORD"}],
    }
    p = _write(tmp_path, app, VALID_PLATFORM)
    cfg = config.load(p)
    assert cfg.app.secrets[0].name == "DB_PASSWORD"
    assert cfg.app.secrets[0].valueEnv == "APP_DB_PASSWORD"


def test_secrets_invalid_name_rejected(tmp_path: Path) -> None:
    app = {**VALID_APP, "secrets": [{"name": "not a name!", "valueEnv": "X"}]}
    p = _write(tmp_path, app, VALID_PLATFORM)
    with pytest.raises(NexusError) as exc_info:
        config.load(p)
    assert "secrets" in exc_info.value.why


def test_secrets_empty_value_env_rejected(tmp_path: Path) -> None:
    app = {**VALID_APP, "secrets": [{"name": "DB_PASSWORD", "valueEnv": ""}]}
    p = _write(tmp_path, app, VALID_PLATFORM)
    with pytest.raises(NexusError) as exc_info:
        config.load(p)
    assert "valueEnv" in exc_info.value.why


def test_secrets_unknown_field_rejected(tmp_path: Path) -> None:
    app = {
        **VALID_APP,
        "secrets": [{"name": "DB_PASSWORD", "valueEnv": "X", "value": "shouldnt-exist"}],
    }
    p = _write(tmp_path, app, VALID_PLATFORM)
    with pytest.raises(NexusError):
        config.load(p)


def test_secret_name_derived_from_app_name(tmp_path: Path) -> None:
    p = _write(tmp_path, VALID_APP, VALID_PLATFORM)
    cfg = config.load(p)
    assert cfg.app.secret_name == f"{cfg.app.name}-secrets"


# --- app.env plaintext-credential guardrail (see docs/INTERVIEW-BRIEF.md) ---
#
# EnvVar.value is deliberately kept free-text at the schema-validator level
# (test_env_value_stays_free_text) — this is a *separate*, narrower check
# that runs after schema validation, in config.load() itself, specifically
# to reject the common case of a real credential ending up in app.env
# instead of app.secrets. It never echoes the rejected value (verified by
# test_credential_value_not_echoed_in_error below) — that's why it's not a
# Pydantic validator (see _validate_no_plaintext_secrets's docstring).


@pytest.mark.parametrize(
    "name", ["DB_PASSWORD", "API_KEY", "APIKEY", "AUTH_TOKEN", "PRIVATE_KEY", "CREDENTIAL_ID"]
)
def test_credential_shaped_env_name_rejected(tmp_path: Path, name: str) -> None:
    app = {**VALID_APP, "env": [{"name": name, "value": "whatever"}]}
    p = _write(tmp_path, app, VALID_PLATFORM)
    with pytest.raises(NexusError) as exc_info:
        config.load(p)
    assert "credential" in exc_info.value.what


@pytest.mark.parametrize(
    "value",
    [
        "postgres://user:hunter2@db.internal:5432/app",
        "https://alice:s3cret@api.example.com/v1",
        "-----BEGIN PRIVATE KEY-----\nMIIBogIBAAJ...",
    ],
)
def test_credential_shaped_env_value_rejected(tmp_path: Path, value: str) -> None:
    app = {**VALID_APP, "env": [{"name": "CONFIG", "value": value}]}
    p = _write(tmp_path, app, VALID_PLATFORM)
    with pytest.raises(NexusError) as exc_info:
        config.load(p)
    assert "credential" in exc_info.value.what


@pytest.mark.parametrize(
    "name,value",
    [
        ("VERSION", "v1"),
        ("BG_COLOR", "blue"),
        ("NODE_ENV", "production"),
    ],
)
def test_ordinary_env_vars_accepted(tmp_path: Path, name: str, value: str) -> None:
    app = {**VALID_APP, "env": [{"name": name, "value": value}]}
    p = _write(tmp_path, app, VALID_PLATFORM)
    cfg = config.load(p)
    assert cfg.app.env[0].value == value


def test_max_tokens_is_a_known_deliberate_false_positive(tmp_path: Path) -> None:
    """MAX_TOKENS isn't a credential, but the deny-list matches on `TOKEN`
    as a substring and flags it anyway — a known, accepted trade-off (the
    deny-list is deliberately biased toward false positives; see its
    comment in config.py). Named here so the trade-off is documented as a
    test, not just a comment, and pinned against `plaintext: true` fixing it.
    """
    app = {**VALID_APP, "env": [{"name": "MAX_TOKENS", "value": "4096"}]}
    p = _write(tmp_path, app, VALID_PLATFORM)
    with pytest.raises(NexusError) as exc_info:
        config.load(p)
    assert "credential" in exc_info.value.what


def test_plaintext_true_bypasses_the_credential_check(tmp_path: Path) -> None:
    app = {
        **VALID_APP,
        "env": [{"name": "MAX_TOKENS", "value": "4096", "plaintext": True}],
    }
    p = _write(tmp_path, app, VALID_PLATFORM)
    cfg = config.load(p)
    assert cfg.app.env[0].value == "4096"


def test_credential_value_not_echoed_in_error(tmp_path: Path) -> None:
    """The whole point of _validate_no_plaintext_secrets living outside
    Pydantic's validator machinery: verified empirically (see
    docs/INTERVIEW-BRIEF.md) that a Pydantic model_validator's error `input`
    echoes the rejected value verbatim — exactly the wrong behavior for a
    check whose job is keeping a credential out of any output at all.
    """
    secret_value = "sk-super-secret-do-not-print-me"
    app = {**VALID_APP, "env": [{"name": "API_KEY", "value": secret_value}]}
    p = _write(tmp_path, app, VALID_PLATFORM)
    with pytest.raises(NexusError) as exc_info:
        config.load(p)
    assert secret_value not in str(exc_info.value)
    assert secret_value not in (exc_info.value.why or "")
    assert secret_value not in (exc_info.value.fix or "")


# --- app.security (pod/container hardening that depends on the image —
# see SecurityConfig's docstring for why these default off, unlike the
# unconditional hardening in deployment.yaml.j2 itself) ---


def test_security_unset_defaults_to_kubernetes_permissive_defaults(tmp_path: Path) -> None:
    p = _write(tmp_path, VALID_APP, VALID_PLATFORM)
    cfg = config.load(p)
    assert cfg.app.security.runAsNonRoot is False
    assert cfg.app.security.runAsUser is None
    assert cfg.app.security.readOnlyRootFilesystem is False


def test_security_valid_config_loads(tmp_path: Path) -> None:
    app = {
        **VALID_APP,
        "security": {"runAsNonRoot": True, "runAsUser": 10001, "readOnlyRootFilesystem": True},
    }
    p = _write(tmp_path, app, VALID_PLATFORM)
    cfg = config.load(p)
    assert cfg.app.security.runAsNonRoot is True
    assert cfg.app.security.runAsUser == 10001
    assert cfg.app.security.readOnlyRootFilesystem is True


def test_security_negative_run_as_user_rejected(tmp_path: Path) -> None:
    app = {**VALID_APP, "security": {"runAsUser": -1}}
    p = _write(tmp_path, app, VALID_PLATFORM)
    with pytest.raises(NexusError):
        config.load(p)


def test_security_unknown_field_rejected(tmp_path: Path) -> None:
    app = {**VALID_APP, "security": {"runAsNonRoot": True, "privileged": True}}
    p = _write(tmp_path, app, VALID_PLATFORM)
    with pytest.raises(NexusError):
        config.load(p)


def test_multiple_credential_shaped_env_vars_all_reported(tmp_path: Path) -> None:
    app = {
        **VALID_APP,
        "env": [
            {"name": "DB_PASSWORD", "value": "x"},
            {"name": "API_KEY", "value": "y"},
        ],
    }
    p = _write(tmp_path, app, VALID_PLATFORM)
    with pytest.raises(NexusError) as exc_info:
        config.load(p)
    assert "DB_PASSWORD" in exc_info.value.what
    assert "API_KEY" in exc_info.value.what
