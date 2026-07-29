"""Tests for the `nexus deploy` command (PRD §7.2, §8)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from nexus_cli.commands import deploy as deploy_module
from nexus_cli.core import argocd, git, helm, preflight
from nexus_cli.core.config import AppConfig, NexusConfig, PlatformConfig
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


def _minimal_config(*, monitoring: bool = True, chaos: bool = False) -> NexusConfig:
    return NexusConfig(
        app=AppConfig(name="my-app", image="repo/app:latest", port=8080, healthPath="/health"),
        platform=PlatformConfig(
            repoURL="https://github.com/user/repo.git",
            branch="main",
            monitoring=monitoring,
            chaos=chaos,
        ),
    )


def _stub_common(monkeypatch: pytest.MonkeyPatch, *, all_installed: bool = True) -> None:
    monkeypatch.setattr(preflight, "ensure_cluster_ready", lambda **k: None)
    monkeypatch.setattr(
        preflight,
        "run",
        lambda **k: [
            preflight.PreflightCheck("kubectl", True, "kubectl found (v1.29.0)"),
            preflight.PreflightCheck("helm", True, "helm found (v3.14.1)"),
            preflight.PreflightCheck("cluster", True, "Cluster reachable -> minikube"),
        ],
    )
    monkeypatch.setattr(helm, "release_exists", lambda release, ns: all_installed)
    monkeypatch.setattr(deploy_module, "apply_app_manifests", lambda cfg: None)
    monkeypatch.setattr(deploy_module, "sync_manifests_to_git", lambda cfg: "pushed to origin/main")
    monkeypatch.setattr(deploy_module, "register_argocd_app", lambda cfg: None)
    monkeypatch.setattr(
        argocd,
        "wait_for_healthy",
        lambda name, timeout=0: argocd.ArgoAppStatus(
            name=name,
            sync_status="Synced",
            health_status="Healthy",
            revision="x",
            last_sync_time="t",
        ),
    )


def test_deploy_preflight_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)

    def fail(**k: object) -> None:
        raise NexusError(what="helm not found")

    monkeypatch.setattr(preflight, "ensure_cluster_ready", fail)
    result = runner.invoke(app, ["deploy"])
    assert result.exit_code != 0
    assert "helm not found" in result.output


def test_deploy_aborts_on_no(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    _stub_common(monkeypatch, all_installed=True)

    result = runner.invoke(app, ["deploy"], input="n\n")
    assert result.exit_code != 0
    assert "Aborted" in result.output


def test_deploy_happy_path_all_deps_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    _stub_common(monkeypatch, all_installed=False)
    monkeypatch.setattr(helm, "repo_add", lambda name, url: None)
    monkeypatch.setattr(helm, "upgrade_install", lambda *a, **k: None)

    result = runner.invoke(app, ["deploy"], input="y\n")
    assert result.exit_code == 0, result.output
    assert "Deployment plan:" in result.output
    assert "1. Install ArgoCD" in result.output
    assert "Apply app manifests" in result.output
    assert "Register ArgoCD app" in result.output
    assert "Synced + Healthy" in result.output
    assert "my-app is live" in result.output
    assert "kubectl -n my-app port-forward svc/my-app" in result.output


def test_deploy_skips_already_installed_deps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    _stub_common(monkeypatch, all_installed=True)

    result = runner.invoke(app, ["deploy"], input="y\n")
    assert result.exit_code == 0, result.output
    assert "present → skip" in result.output
    assert "1. Apply app manifests" in result.output
    assert "2. Commit manifests to Git" in result.output
    assert "3. Register ArgoCD app" in result.output
    assert "pushed to origin/main" in result.output


def test_deploy_yes_flag_skips_prompt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    _stub_common(monkeypatch, all_installed=True)

    result = runner.invoke(app, ["deploy", "--yes"])
    assert result.exit_code == 0, result.output
    assert "is live" in result.output


def test_deploy_step_failure_stops_and_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    _stub_common(monkeypatch, all_installed=True)

    calls: list[str] = []

    def failing_apply(cfg: object) -> None:
        calls.append("apply")
        raise NexusError(what="kubectl apply failed", why="bad manifest")

    def spy_register(cfg: object) -> None:
        calls.append("register")

    monkeypatch.setattr(deploy_module, "apply_app_manifests", failing_apply)
    monkeypatch.setattr(deploy_module, "register_argocd_app", spy_register)

    result = runner.invoke(app, ["deploy", "--yes"])
    assert result.exit_code != 0
    assert "aborted at this step" in result.output
    assert "bad manifest" in result.output
    assert "register" not in calls


def test_deploy_sync_wait_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    _stub_common(monkeypatch, all_installed=True)

    def fail_wait(name: str, timeout: int = 0) -> argocd.ArgoAppStatus:
        raise NexusError(what=f"Application '{name}' did not become Synced + Healthy")

    monkeypatch.setattr(argocd, "wait_for_healthy", fail_wait)

    result = runner.invoke(app, ["deploy", "--yes"])
    assert result.exit_code != 0
    assert "did not become Synced" in result.output
    assert "check with `nexus status`" in result.output


def test_install_monitoring_enables_grafana_iframe_embedding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Grafana denies framing by default, which would break the dashboard's
    embedded panels (PRD §10.4). Pin both the settings and the `--set` escaping.
    """
    captured: dict[str, object] = {}
    monkeypatch.setattr(helm, "repo_add", lambda name, url: None)
    monkeypatch.setattr(
        helm,
        "upgrade_install",
        lambda release, chart, **kwargs: captured.update(kwargs),
    )

    deploy_module._install_monitoring()

    values = captured["values"]
    assert values == {
        "grafana.grafana\\.ini.security.allow_embedding": "true",
        "grafana.grafana\\.ini.security.cookie_samesite": "lax",
    }
    # helm --set treats "." as a path separator, so the dot inside the
    # `grafana.ini` value key must stay escaped or the setting lands nowhere.
    assert all("grafana\\.ini" in key for key in values)


def test_dependency_status_all_flags_off(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _minimal_config(monitoring=False, chaos=False)
    monkeypatch.setattr(helm, "release_exists", lambda release, ns: False)
    deps = deploy_module.dependency_status(cfg)
    assert [d[0] for d in deps] == ["ArgoCD"]


def test_dependency_status_monitoring_and_chaos_on(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _minimal_config(monitoring=True, chaos=True)
    monkeypatch.setattr(helm, "release_exists", lambda release, ns: False)
    deps = deploy_module.dependency_status(cfg)
    assert [d[0] for d in deps] == ["ArgoCD", "kube-prometheus-stack", "Chaos Mesh"]


def test_apply_app_manifests_skips_argocd_app(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _minimal_config()
    applied: list[str] = []
    monkeypatch.setattr(
        deploy_module.render,
        "render_manifests",
        lambda c: {"namespace": "ns-yaml", "deployment": "deploy-yaml", "argocd-app": "argo-yaml"},
    )
    monkeypatch.setattr(deploy_module.kubectl, "apply_manifest", lambda text: applied.append(text))
    deploy_module.apply_app_manifests(cfg)
    assert "argo-yaml" not in applied
    assert "ns-yaml" in applied
    assert "deploy-yaml" in applied


def test_register_argocd_app_registers_only_the_argocd_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = _minimal_config()
    registered: list[str] = []
    monkeypatch.setattr(
        deploy_module.render,
        "render_manifests",
        lambda c: {"argocd-app": "argo-yaml", "namespace": "ns"},
    )
    monkeypatch.setattr(deploy_module.argocd, "register", lambda text: registered.append(text))
    synced: list[str] = []
    monkeypatch.setattr(deploy_module.argocd, "trigger_sync", lambda name: synced.append(name))
    deploy_module.register_argocd_app(cfg)
    assert registered == ["argo-yaml"]
    assert synced == ["my-app"]


# --- sync_manifests_to_git ---


def test_sync_manifests_not_a_repo_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(git, "is_repo", lambda: False)
    cfg = _minimal_config()
    with pytest.raises(NexusError) as exc_info:
        deploy_module.sync_manifests_to_git(cfg)
    assert "not a git repository" in exc_info.value.what


def test_sync_manifests_branch_mismatch_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(git, "is_repo", lambda: True)
    monkeypatch.setattr(git, "current_branch", lambda: "feature-x")
    cfg = _minimal_config()  # platform.branch == "main"
    with pytest.raises(NexusError) as exc_info:
        deploy_module.sync_manifests_to_git(cfg)
    assert "does not match platform.branch" in exc_info.value.what


def test_sync_manifests_no_remote_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(git, "is_repo", lambda: True)
    monkeypatch.setattr(git, "current_branch", lambda: "main")
    monkeypatch.setattr(git, "default_remote", lambda: None)
    cfg = _minimal_config()
    with pytest.raises(NexusError) as exc_info:
        deploy_module.sync_manifests_to_git(cfg)
    assert "No git remote" in exc_info.value.what


def test_sync_manifests_up_to_date_skips_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(git, "is_repo", lambda: True)
    monkeypatch.setattr(git, "current_branch", lambda: "main")
    monkeypatch.setattr(git, "default_remote", lambda: "origin")
    monkeypatch.setattr(git, "add", lambda paths: None)
    monkeypatch.setattr(git, "has_staged_changes", lambda: False)
    committed: list[str] = []
    monkeypatch.setattr(git, "commit", lambda msg: committed.append(msg))
    cfg = _minimal_config()
    outcome = deploy_module.sync_manifests_to_git(cfg)
    assert "nothing to commit" in outcome
    assert committed == []


def test_sync_manifests_commits_and_pushes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(git, "is_repo", lambda: True)
    monkeypatch.setattr(git, "current_branch", lambda: "main")
    monkeypatch.setattr(git, "default_remote", lambda: "origin")
    added: list[list[str]] = []
    monkeypatch.setattr(git, "add", lambda paths: added.append(paths))
    monkeypatch.setattr(git, "has_staged_changes", lambda: True)
    committed: list[str] = []
    monkeypatch.setattr(git, "commit", lambda msg: committed.append(msg))
    pushed: list[tuple[str, str]] = []
    monkeypatch.setattr(git, "push", lambda remote, branch: pushed.append((remote, branch)))

    cfg = _minimal_config()
    outcome = deploy_module.sync_manifests_to_git(cfg)

    assert added == [[deploy_module.MANIFESTS_DIR]]
    assert committed == ["nexus: sync k8s manifests for my-app"]
    assert pushed == [("origin", "main")]
    assert outcome == "pushed to origin/main"

    manifests_dir = tmp_path / deploy_module.MANIFESTS_DIR
    assert manifests_dir.is_dir()
    assert (manifests_dir / "namespace.yaml").is_file()
    assert not (manifests_dir / "argocd-app.yaml").exists()  # excluded, per apply_app_manifests
