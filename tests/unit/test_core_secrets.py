"""Unit tests for nexus_cli.core.secrets (app.secrets automation).

Mocked kubectl/subprocess throughout — no real cluster. Modeled directly on
tests/unit/test_core_registry.py, which covers the identical pattern for
imagePullSecrets.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nexus_cli.core import secrets
from nexus_cli.core.config import AppConfig, SecretVar
from nexus_cli.core.output import NexusError


def _app(**overrides: object) -> AppConfig:
    defaults: dict[str, object] = {
        "name": "my-app",
        "image": "ghcr.io/me/my-app:v1",
        "port": 8080,
        "healthPath": "/health",
        "secrets": [
            SecretVar(name="DB_PASSWORD", valueEnv="APP_DB_PASSWORD"),
            SecretVar(name="API_KEY", valueEnv="APP_API_KEY"),
        ],
    }
    defaults.update(overrides)
    return AppConfig.model_validate(defaults)


# --- resolve_values ---


def test_resolve_values_reads_named_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_DB_PASSWORD", "hunter2")
    monkeypatch.setenv("APP_API_KEY", "sk-abc123")
    values = secrets.resolve_values(_app())
    assert values == {"DB_PASSWORD": "hunter2", "API_KEY": "sk-abc123"}


def test_resolve_values_raises_when_one_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APP_DB_PASSWORD", raising=False)
    monkeypatch.setenv("APP_API_KEY", "sk-abc123")
    with pytest.raises(NexusError) as exc_info:
        secrets.resolve_values(_app())
    assert "APP_DB_PASSWORD" in exc_info.value.what
    assert "APP_API_KEY" not in exc_info.value.what


def test_resolve_values_raises_when_all_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APP_DB_PASSWORD", raising=False)
    monkeypatch.delenv("APP_API_KEY", raising=False)
    with pytest.raises(NexusError) as exc_info:
        secrets.resolve_values(_app())
    assert "APP_DB_PASSWORD" in exc_info.value.what
    assert "APP_API_KEY" in exc_info.value.what


def test_resolve_values_raises_on_empty_string_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_DB_PASSWORD", "")
    monkeypatch.setenv("APP_API_KEY", "sk-abc123")
    with pytest.raises(NexusError) as exc_info:
        secrets.resolve_values(_app())
    assert "APP_DB_PASSWORD" in exc_info.value.what


def test_no_secret_value_appears_in_the_nexus_error_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The missing-env-var error names the env var, never a value — there's
    no value to leak when it's missing, but this pins that resolve_values
    never echoes app.secrets[].name-derived values either.
    """
    monkeypatch.delenv("APP_DB_PASSWORD", raising=False)
    monkeypatch.setenv("APP_API_KEY", "sk-super-secret-value")
    with pytest.raises(NexusError) as exc_info:
        secrets.resolve_values(_app())
    assert "sk-super-secret-value" not in str(exc_info.value)


# --- apply_app_secret ---


def test_apply_app_secret_noop_when_secrets_unset() -> None:
    app = AppConfig.model_validate(
        {"name": "my-app", "image": "myrepo/app:v1", "port": 8080, "healthPath": "/health"}
    )
    # Must not raise, and must not attempt any kubectl call — proven by the
    # absence of any mocking/patching here: a real kubectl.run call would
    # fail loudly (kubectl likely isn't even on PATH in the test env), the
    # same proof pattern test_core_registry.py uses.
    secrets.apply_app_secret(app)


def test_apply_app_secret_creates_secret_via_dry_run_apply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_DB_PASSWORD", "hunter2")
    monkeypatch.setenv("APP_API_KEY", "sk-abc123")

    run_calls: list[list[str]] = []
    applied: list[str] = []
    written_temp_files: dict[str, str] = {}

    def fake_run(args: list[str], **kwargs: object) -> object:
        run_calls.append(args)
        for arg in args:
            if arg.startswith("--from-file="):
                key_and_path = arg.removeprefix("--from-file=")
                key, path = key_and_path.split("=", 1)
                written_temp_files[key] = Path(path).read_text()

        class _Result:
            stdout = "apiVersion: v1\nkind: Secret\n"

        return _Result()

    def fake_apply_manifest(text: str) -> None:
        applied.append(text)

    monkeypatch.setattr(secrets.kubectl, "run", fake_run)
    monkeypatch.setattr(secrets.kubectl, "apply_manifest", fake_apply_manifest)

    secrets.apply_app_secret(_app())

    assert len(run_calls) == 1
    args = run_calls[0]
    assert args[:4] == ["create", "secret", "generic", "my-app-secrets"]
    assert "-n" in args and args[args.index("-n") + 1] == "my-app"
    assert "--dry-run=client" in args
    # never a --from-literal=... (would leak the value into argv/ps aux)
    assert not any(a.startswith("--from-literal=") for a in args)

    assert written_temp_files == {"DB_PASSWORD": "hunter2", "API_KEY": "sk-abc123"}
    assert applied == ["apiVersion: v1\nkind: Secret\n"]


def test_apply_app_secret_deletes_all_temp_files_even_on_kubectl_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_DB_PASSWORD", "hunter2")
    monkeypatch.setenv("APP_API_KEY", "sk-abc123")

    captured_paths: list[str] = []

    def fake_run(args: list[str], **kwargs: object) -> object:
        for arg in args:
            if arg.startswith("--from-file="):
                captured_paths.append(arg.split("=", 2)[2])
        raise NexusError(what="kubectl create secret failed.")

    monkeypatch.setattr(secrets.kubectl, "run", fake_run)

    with pytest.raises(NexusError):
        secrets.apply_app_secret(_app())

    assert len(captured_paths) == 2
    for path in captured_paths:
        assert not Path(path).exists()


def test_apply_app_secret_temp_files_are_owner_only_readable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_DB_PASSWORD", "hunter2")
    monkeypatch.setenv("APP_API_KEY", "sk-abc123")

    modes: list[int] = []

    def fake_run(args: list[str], **kwargs: object) -> object:
        for arg in args:
            if arg.startswith("--from-file="):
                path = Path(arg.split("=", 2)[2])
                modes.append(path.stat().st_mode & 0o777)

        class _Result:
            stdout = "apiVersion: v1\nkind: Secret\n"

        return _Result()

    monkeypatch.setattr(secrets.kubectl, "run", fake_run)
    monkeypatch.setattr(secrets.kubectl, "apply_manifest", lambda text: None)

    secrets.apply_app_secret(_app())

    assert modes == [0o600, 0o600]
