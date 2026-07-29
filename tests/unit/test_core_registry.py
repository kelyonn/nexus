"""Unit tests for nexus_cli.core.registry (imagePullSecrets automation).

Mocked kubectl/subprocess throughout — no real cluster, no real Docker
registry. Live verification against a real authenticated registry happened
manually; see CHANGELOG.md.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from nexus_cli.core import registry
from nexus_cli.core.config import AppConfig, RegistryConfig
from nexus_cli.core.output import NexusError


def _app(**overrides: object) -> AppConfig:
    defaults: dict[str, object] = {
        "name": "my-app",
        "image": "ghcr.io/me/my-app:v1",
        "port": 8080,
        "healthPath": "/health",
        "registry": RegistryConfig(
            server="ghcr.io", usernameEnv="REG_USER", passwordEnv="REG_PASS"
        ),
    }
    defaults.update(overrides)
    return AppConfig.model_validate(defaults)


# --- resolve_credentials ---


def test_resolve_credentials_reads_named_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REG_USER", "alice")
    monkeypatch.setenv("REG_PASS", "s3cret")
    username, password = registry.resolve_credentials(_app())
    assert username == "alice"
    assert password == "s3cret"


def test_resolve_credentials_raises_when_username_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("REG_USER", raising=False)
    monkeypatch.setenv("REG_PASS", "s3cret")
    with pytest.raises(NexusError) as exc_info:
        registry.resolve_credentials(_app())
    assert "REG_USER" in exc_info.value.what
    assert "REG_PASS" not in exc_info.value.what


def test_resolve_credentials_raises_when_both_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("REG_USER", raising=False)
    monkeypatch.delenv("REG_PASS", raising=False)
    with pytest.raises(NexusError) as exc_info:
        registry.resolve_credentials(_app())
    assert "REG_USER" in exc_info.value.what
    assert "REG_PASS" in exc_info.value.what


def test_resolve_credentials_raises_when_env_var_is_empty_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty-string credential is a config mistake worth catching up
    front — silently creating a Secret that can't authenticate is a worse
    failure mode (a confusing ImagePullBackOff much later).
    """
    monkeypatch.setenv("REG_USER", "")
    monkeypatch.setenv("REG_PASS", "s3cret")
    with pytest.raises(NexusError) as exc_info:
        registry.resolve_credentials(_app())
    assert "REG_USER" in exc_info.value.what


# --- _docker_config_json ---


def test_docker_config_json_shape_and_auth_encoding() -> None:
    text = registry._docker_config_json("ghcr.io", "alice", "s3cret")
    data = json.loads(text)
    assert data["auths"]["ghcr.io"]["username"] == "alice"
    assert data["auths"]["ghcr.io"]["password"] == "s3cret"
    decoded = base64.b64decode(data["auths"]["ghcr.io"]["auth"]).decode()
    assert decoded == "alice:s3cret"


# --- apply_pull_secret ---


def test_apply_pull_secret_noop_when_registry_unset() -> None:
    app = AppConfig.model_validate(
        {"name": "my-app", "image": "myrepo/app:v1", "port": 8080, "healthPath": "/health"}
    )
    # Must not raise, and must not attempt any kubectl call — proven by the
    # absence of any mocking/patching here: a real kubectl.run call would
    # fail loudly (kubectl likely isn't even on PATH in the test env).
    registry.apply_pull_secret(app)


def test_apply_pull_secret_creates_dockerconfigjson_secret_via_dry_run_apply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REG_USER", "alice")
    monkeypatch.setenv("REG_PASS", "s3cret")

    run_calls: list[list[str]] = []
    applied: list[str] = []
    written_temp_files: list[str] = []

    def fake_run(args: list[str], **kwargs: object) -> object:
        run_calls.append(args)
        # Capture what was actually written to the --from-file path so we
        # can assert on real file content, not just the argv shape.
        for arg in args:
            if arg.startswith("--from-file=.dockerconfigjson="):
                path = arg.split("=", 2)[2]
                written_temp_files.append(Path(path).read_text())

        class _Result:
            stdout = "apiVersion: v1\nkind: Secret\n"

        return _Result()

    def fake_apply_manifest(text: str) -> None:
        applied.append(text)

    monkeypatch.setattr(registry.kubectl, "run", fake_run)
    monkeypatch.setattr(registry.kubectl, "apply_manifest", fake_apply_manifest)

    registry.apply_pull_secret(_app())

    assert len(run_calls) == 1
    args = run_calls[0]
    assert args[:4] == ["create", "secret", "generic", "my-app-registry"]
    assert "--type=kubernetes.io/dockerconfigjson" in args
    assert "-n" in args and args[args.index("-n") + 1] == "my-app"
    assert "--dry-run=client" in args

    assert len(written_temp_files) == 1
    config_data = json.loads(written_temp_files[0])
    assert config_data["auths"]["ghcr.io"]["username"] == "alice"
    assert config_data["auths"]["ghcr.io"]["password"] == "s3cret"

    assert applied == ["apiVersion: v1\nkind: Secret\n"]


def test_apply_pull_secret_deletes_temp_file_even_on_kubectl_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REG_USER", "alice")
    monkeypatch.setenv("REG_PASS", "s3cret")

    captured_path: dict[str, str] = {}

    def fake_run(args: list[str], **kwargs: object) -> object:
        for arg in args:
            if arg.startswith("--from-file=.dockerconfigjson="):
                captured_path["path"] = arg.split("=", 2)[2]
        raise NexusError(what="kubectl create secret failed.")

    monkeypatch.setattr(registry.kubectl, "run", fake_run)

    with pytest.raises(NexusError):
        registry.apply_pull_secret(_app())

    assert "path" in captured_path
    assert not Path(captured_path["path"]).exists()


def test_apply_pull_secret_temp_file_is_owner_only_readable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole point of writing credentials to a temp file instead of a
    --docker-password=... CLI argument is to avoid leaking them to anything
    that can read this process's argv — that only holds if the temp file
    itself isn't world/group readable while it briefly exists.
    """
    monkeypatch.setenv("REG_USER", "alice")
    monkeypatch.setenv("REG_PASS", "s3cret")

    modes: list[int] = []

    def fake_run(args: list[str], **kwargs: object) -> object:
        for arg in args:
            if arg.startswith("--from-file=.dockerconfigjson="):
                path = Path(arg.split("=", 2)[2])
                modes.append(path.stat().st_mode & 0o777)

        class _Result:
            stdout = "apiVersion: v1\nkind: Secret\n"

        return _Result()

    monkeypatch.setattr(registry.kubectl, "run", fake_run)
    monkeypatch.setattr(registry.kubectl, "apply_manifest", lambda text: None)

    registry.apply_pull_secret(_app())

    assert modes == [0o600]
