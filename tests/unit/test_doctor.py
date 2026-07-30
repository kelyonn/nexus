"""Tests for `nexus doctor` (PRD §12, §15)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from nexus_cli.commands import doctor as doctor_module
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


def _healthy_preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor_module.kubectl, "version_client", lambda: "v1.29.0")
    monkeypatch.setattr(doctor_module.helm, "version", lambda: "v3.14.1")
    monkeypatch.setattr(doctor_module.kubectl, "current_context", lambda: "minikube")
    monkeypatch.setattr(doctor_module.kubectl, "cluster_reachable", lambda: True)


def test_doctor_all_green(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    _healthy_preflight(monkeypatch)
    monkeypatch.setattr(doctor_module.kubectl, "can_i", lambda *a, **k: True)
    monkeypatch.setattr(doctor_module.git, "is_repo", lambda: True)
    monkeypatch.setattr(doctor_module.git, "current_branch", lambda: "main")
    monkeypatch.setattr(doctor_module.git, "default_remote", lambda: "origin")
    monkeypatch.setattr(doctor_module.helm, "release_exists", lambda *a, **k: True)

    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert "Everything looks good" in result.output
    assert "ArgoCD installed" in result.output


def test_doctor_missing_kubectl_reports_fix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(doctor_module.kubectl, "version_client", lambda: None)
    monkeypatch.setattr(doctor_module.helm, "version", lambda: "v3.14.1")
    monkeypatch.setattr(doctor_module.kubectl, "current_context", lambda: None)
    monkeypatch.setattr(doctor_module.kubectl, "cluster_reachable", lambda: False)

    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "kubectl not found" in result.output
    assert "Install it: https://kubernetes.io/docs/tasks/tools/#kubectl" in result.output
    assert "problem(s) found" in result.output


def test_doctor_skips_rbac_when_cluster_unreachable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(doctor_module.kubectl, "version_client", lambda: "v1.29.0")
    monkeypatch.setattr(doctor_module.helm, "version", lambda: "v3.14.1")
    monkeypatch.setattr(doctor_module.kubectl, "current_context", lambda: None)
    monkeypatch.setattr(doctor_module.kubectl, "cluster_reachable", lambda: False)

    called = {"can_i": False}

    def spy_can_i(*a: object, **k: object) -> bool:
        called["can_i"] = True
        return True

    monkeypatch.setattr(doctor_module.kubectl, "can_i", spy_can_i)

    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert called["can_i"] is False
    assert "Platform components" not in result.output


def test_doctor_reports_missing_rbac_permissions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _healthy_preflight(monkeypatch)
    monkeypatch.setattr(
        doctor_module.kubectl,
        "can_i",
        lambda verb, resource, **k: not (verb == "create" and resource == "namespaces"),
    )
    monkeypatch.setattr(doctor_module.helm, "release_exists", lambda *a, **k: False)

    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "cannot create namespaces" in result.output


def test_doctor_no_config_reports_fix_but_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _healthy_preflight(monkeypatch)
    monkeypatch.setattr(doctor_module.kubectl, "can_i", lambda *a, **k: True)
    monkeypatch.setattr(doctor_module.helm, "release_exists", lambda *a, **k: False)

    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "No nexus.yaml found" in result.output
    assert "nexus init" in result.output
    # No config means no git check should have run at all.
    assert "git OK" not in result.output and "not a git repository" not in result.output


def test_doctor_invalid_config_reports_validation_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "nexus.yaml").write_text("app:\n  name: Bad_Name\n")
    _healthy_preflight(monkeypatch)
    monkeypatch.setattr(doctor_module.kubectl, "can_i", lambda *a, **k: True)
    monkeypatch.setattr(doctor_module.helm, "release_exists", lambda *a, **k: False)

    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "Invalid nexus.yaml" in result.output
    assert "app.name" in result.output  # field-level detail, not just "invalid"


def test_doctor_reports_branch_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    _healthy_preflight(monkeypatch)
    monkeypatch.setattr(doctor_module.kubectl, "can_i", lambda *a, **k: True)
    monkeypatch.setattr(doctor_module.git, "is_repo", lambda: True)
    monkeypatch.setattr(doctor_module.git, "current_branch", lambda: "not-main")
    monkeypatch.setattr(doctor_module.git, "default_remote", lambda: "origin")
    monkeypatch.setattr(doctor_module.helm, "release_exists", lambda *a, **k: False)

    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "not-main" in result.output and "platform.branch" in result.output


def test_doctor_reports_not_a_git_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    _healthy_preflight(monkeypatch)
    monkeypatch.setattr(doctor_module.kubectl, "can_i", lambda *a, **k: True)
    monkeypatch.setattr(doctor_module.git, "is_repo", lambda: False)
    monkeypatch.setattr(doctor_module.helm, "release_exists", lambda *a, **k: False)

    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "not a git repository" in result.output


VALID_YAML_WITH_REGISTRY = """
app:
  name: my-app
  image: ghcr.io/me/my-app:latest
  port: 8080
  healthPath: /health
  registry:
    server: ghcr.io
    usernameEnv: REGISTRY_USERNAME
    passwordEnv: REGISTRY_PASSWORD
platform:
  repoURL: https://github.com/user/repo.git
  branch: main
"""


def _write_config_with_registry(tmp_path: Path) -> Path:
    p = tmp_path / "nexus.yaml"
    p.write_text(VALID_YAML_WITH_REGISTRY)
    return p


def test_doctor_no_registry_configured_reports_nothing_about_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """app.registry unset (the default/most common case) shouldn't show a
    registry line in the report at all — only apps that opted in are
    checked.
    """
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    _healthy_preflight(monkeypatch)
    monkeypatch.setattr(doctor_module.kubectl, "can_i", lambda *a, **k: True)
    monkeypatch.setattr(doctor_module.git, "is_repo", lambda: True)
    monkeypatch.setattr(doctor_module.git, "current_branch", lambda: "main")
    monkeypatch.setattr(doctor_module.git, "default_remote", lambda: "origin")
    monkeypatch.setattr(doctor_module.helm, "release_exists", lambda *a, **k: True)

    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert "registry" not in result.output.lower()


def test_doctor_reports_missing_registry_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config_with_registry(tmp_path)
    monkeypatch.delenv("REGISTRY_USERNAME", raising=False)
    monkeypatch.delenv("REGISTRY_PASSWORD", raising=False)
    _healthy_preflight(monkeypatch)
    monkeypatch.setattr(doctor_module.kubectl, "can_i", lambda *a, **k: True)
    monkeypatch.setattr(doctor_module.git, "is_repo", lambda: True)
    monkeypatch.setattr(doctor_module.git, "current_branch", lambda: "main")
    monkeypatch.setattr(doctor_module.git, "default_remote", lambda: "origin")
    monkeypatch.setattr(doctor_module.helm, "release_exists", lambda *a, **k: True)

    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "REGISTRY_USERNAME" in result.output
    assert "REGISTRY_PASSWORD" in result.output
    # Never print the actual credential values, even if they happen to be set.
    assert "hunter2" not in result.output


def test_doctor_registry_credentials_present_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config_with_registry(tmp_path)
    monkeypatch.setenv("REGISTRY_USERNAME", "alice")
    monkeypatch.setenv("REGISTRY_PASSWORD", "hunter2")
    _healthy_preflight(monkeypatch)
    monkeypatch.setattr(doctor_module.kubectl, "can_i", lambda *a, **k: True)
    monkeypatch.setattr(doctor_module.git, "is_repo", lambda: True)
    monkeypatch.setattr(doctor_module.git, "current_branch", lambda: "main")
    monkeypatch.setattr(doctor_module.git, "default_remote", lambda: "origin")
    monkeypatch.setattr(doctor_module.helm, "release_exists", lambda *a, **k: True)

    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert "Everything looks good" in result.output
    assert "hunter2" not in result.output  # never echo the actual credential


VALID_YAML_WITH_APP_SECRETS = """
app:
  name: my-app
  image: myrepo/app:latest
  port: 8080
  healthPath: /health
  secrets:
    - name: DB_PASSWORD
      valueEnv: APP_DB_PASSWORD
platform:
  repoURL: https://github.com/user/repo.git
  branch: main
"""


def _write_config_with_app_secrets(tmp_path: Path) -> Path:
    p = tmp_path / "nexus.yaml"
    p.write_text(VALID_YAML_WITH_APP_SECRETS)
    return p


def test_doctor_no_secrets_configured_reports_nothing_about_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """app.secrets unset (the default/most common case) shouldn't run the
    app.secrets-specific check at all — same reasoning as the registry
    check. (The RBAC line legitimately mentions "secrets" generically, since
    that permission is needed for app.registry too — this checks the
    secrets-specific DoctorCheck line, not the word "secrets" anywhere.)
    """
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    _healthy_preflight(monkeypatch)
    monkeypatch.setattr(doctor_module.kubectl, "can_i", lambda *a, **k: True)
    monkeypatch.setattr(doctor_module.git, "is_repo", lambda: True)
    monkeypatch.setattr(doctor_module.git, "current_branch", lambda: "main")
    monkeypatch.setattr(doctor_module.git, "default_remote", lambda: "origin")
    monkeypatch.setattr(doctor_module.helm, "release_exists", lambda *a, **k: True)

    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert "app.secrets env vars" not in result.output
    assert "Secret env var(s)" not in result.output


def test_doctor_reports_missing_secret_env_vars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config_with_app_secrets(tmp_path)
    monkeypatch.delenv("APP_DB_PASSWORD", raising=False)
    _healthy_preflight(monkeypatch)
    monkeypatch.setattr(doctor_module.kubectl, "can_i", lambda *a, **k: True)
    monkeypatch.setattr(doctor_module.git, "is_repo", lambda: True)
    monkeypatch.setattr(doctor_module.git, "current_branch", lambda: "main")
    monkeypatch.setattr(doctor_module.git, "default_remote", lambda: "origin")
    monkeypatch.setattr(doctor_module.helm, "release_exists", lambda *a, **k: True)

    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "APP_DB_PASSWORD" in result.output


def test_doctor_secret_env_vars_present_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config_with_app_secrets(tmp_path)
    monkeypatch.setenv("APP_DB_PASSWORD", "hunter2")
    _healthy_preflight(monkeypatch)
    monkeypatch.setattr(doctor_module.kubectl, "can_i", lambda *a, **k: True)
    monkeypatch.setattr(doctor_module.git, "is_repo", lambda: True)
    monkeypatch.setattr(doctor_module.git, "current_branch", lambda: "main")
    monkeypatch.setattr(doctor_module.git, "default_remote", lambda: "origin")
    monkeypatch.setattr(doctor_module.helm, "release_exists", lambda *a, **k: True)

    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert "Everything looks good" in result.output
    assert "hunter2" not in result.output  # never echo the actual secret value


def test_doctor_rbac_check_mentions_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    """app.registry and app.secrets both need `create secrets` RBAC — the
    check should name it, not just namespaces/deployments.
    """
    monkeypatch.setattr(
        doctor_module.kubectl,
        "can_i",
        lambda verb, resource, **k: not (verb == "create" and resource == "secrets"),
    )
    check = doctor_module._check_rbac()
    assert check.passed is False
    assert "create secrets" in check.detail


def test_doctor_platform_components_not_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _healthy_preflight(monkeypatch)
    monkeypatch.setattr(doctor_module.kubectl, "can_i", lambda *a, **k: True)
    monkeypatch.setattr(doctor_module.helm, "release_exists", lambda *a, **k: False)

    result = runner.invoke(app, ["doctor"])
    assert "Chaos Mesh not installed" in result.output
