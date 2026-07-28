"""Tests for the `nexus upgrade` command (PRD §7.9).

Mirrors deploy/status/logs/chaos's CliRunner + monkeypatch pattern. `gitops.
check_git_preconditions` and `gitops.apply_image_change` are stubbed here
(their own correctness is covered by test_gitops.py) so these tests stay
focused on `upgrade`'s own orchestration: safety-check ordering, the
same-image no-op, --dry-run, and the sync/wait/report tail.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from nexus_cli.commands import upgrade as upgrade_module
from nexus_cli.core import argocd, gitops, preflight
from nexus_cli.core.output import NexusError
from nexus_cli.main import app

runner = CliRunner()

VALID_YAML = """
app:
  name: my-app
  image: myrepo/app:v1
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


def _ok_preconditions(
    *, branch_matches: bool = True, branch: str = "main"
) -> gitops.GitPreconditions:
    return gitops.GitPreconditions(remote="origin", branch=branch, branch_matches=branch_matches)


def _setup_common(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    monkeypatch.setattr(preflight, "ensure_cluster_ready", lambda **k: None)


def test_upgrade_preflight_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)

    def fail(**k: object) -> None:
        raise NexusError(what="cluster not reachable")

    monkeypatch.setattr(preflight, "ensure_cluster_ready", fail)
    result = runner.invoke(app, ["upgrade", "--image", "myrepo/app:v2"])
    assert result.exit_code != 0
    assert "cluster not reachable" in result.output


def test_upgrade_git_precondition_failure_surfaces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_common(tmp_path, monkeypatch)

    def fail(cfg: object) -> gitops.GitPreconditions:
        raise NexusError(what="Current directory is not a git repository.")

    monkeypatch.setattr(upgrade_module.gitops, "check_git_preconditions", fail)
    result = runner.invoke(app, ["upgrade", "--image", "myrepo/app:v2"])
    assert result.exit_code != 0
    assert "not a git repository" in result.output


def test_upgrade_branch_mismatch_decline_aborts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_common(tmp_path, monkeypatch)
    monkeypatch.setattr(
        upgrade_module.gitops,
        "check_git_preconditions",
        lambda cfg: _ok_preconditions(branch_matches=False, branch="other-branch"),
    )
    applied = {"called": False}
    monkeypatch.setattr(
        upgrade_module.gitops,
        "apply_image_change",
        lambda *a, **k: applied.__setitem__("called", True) or True,
    )

    result = runner.invoke(app, ["upgrade", "--image", "myrepo/app:v2"], input="n\n")
    assert result.exit_code != 0
    assert "Aborted" in result.output
    assert applied["called"] is False


def test_upgrade_branch_mismatch_confirm_proceeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_common(tmp_path, monkeypatch)
    monkeypatch.setattr(
        upgrade_module.gitops,
        "check_git_preconditions",
        lambda cfg: _ok_preconditions(branch_matches=False, branch="other-branch"),
    )
    monkeypatch.setattr(upgrade_module.gitops, "apply_image_change", lambda *a, **k: True)
    monkeypatch.setattr(upgrade_module.argocd, "trigger_sync", lambda name: None)
    monkeypatch.setattr(
        upgrade_module.argocd,
        "wait_for_healthy",
        lambda name, **k: argocd.ArgoAppStatus(
            name=name,
            sync_status="Synced",
            health_status="Healthy",
            revision="x",
            last_sync_time="t",
        ),
    )
    monkeypatch.setattr(upgrade_module.gitops, "summarize_pods", lambda ns: [])

    result = runner.invoke(app, ["upgrade", "--image", "myrepo/app:v2"], input="y\ny\n")
    assert result.exit_code == 0, result.output
    assert "upgraded to myrepo/app:v2" in result.output


def test_upgrade_same_image_is_noop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_common(tmp_path, monkeypatch)
    monkeypatch.setattr(
        upgrade_module.gitops, "check_git_preconditions", lambda cfg: _ok_preconditions()
    )
    called = {"apply": False}
    monkeypatch.setattr(
        upgrade_module.gitops,
        "apply_image_change",
        lambda *a, **k: called.__setitem__("apply", True) or True,
    )

    result = runner.invoke(app, ["upgrade", "--image", "myrepo/app:v1"])  # same as current
    assert result.exit_code == 0, result.output
    assert "Already at that image" in result.output
    assert called["apply"] is False


def test_upgrade_invalid_image_format_errors_before_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_common(tmp_path, monkeypatch)
    monkeypatch.setattr(
        upgrade_module.gitops, "check_git_preconditions", lambda cfg: _ok_preconditions()
    )
    called = {"apply": False}
    monkeypatch.setattr(
        upgrade_module.gitops,
        "apply_image_change",
        lambda *a, **k: called.__setitem__("apply", True) or True,
    )

    result = runner.invoke(app, ["upgrade", "--image", "no-tag-here"])
    assert result.exit_code != 0
    assert called["apply"] is False
    # the file on disk must be untouched
    assert (tmp_path / "nexus.yaml").read_text() == VALID_YAML


def test_upgrade_dry_run_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_common(tmp_path, monkeypatch)
    monkeypatch.setattr(
        upgrade_module.gitops, "check_git_preconditions", lambda cfg: _ok_preconditions()
    )
    called = {"apply": False}
    monkeypatch.setattr(
        upgrade_module.gitops,
        "apply_image_change",
        lambda *a, **k: called.__setitem__("apply", True) or True,
    )

    result = runner.invoke(app, ["upgrade", "--image", "myrepo/app:v2", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "Dry run" in result.output
    assert called["apply"] is False
    assert (tmp_path / "nexus.yaml").read_text() == VALID_YAML
    assert not (tmp_path / "k8s").exists()


def test_upgrade_dry_run_skips_branch_mismatch_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--dry-run must never block on a confirmation, even with a branch
    mismatch — it's documented as a side-effect-free preview. No `input=` is
    passed here on purpose: if the branch-mismatch prompt fired, CliRunner
    would hit EOF on stdin and the command would abort instead of reaching
    the dry-run message.
    """
    _setup_common(tmp_path, monkeypatch)
    monkeypatch.setattr(
        upgrade_module.gitops,
        "check_git_preconditions",
        lambda cfg: _ok_preconditions(branch_matches=False, branch="other-branch"),
    )
    called = {"apply": False}
    monkeypatch.setattr(
        upgrade_module.gitops,
        "apply_image_change",
        lambda *a, **k: called.__setitem__("apply", True) or True,
    )

    result = runner.invoke(app, ["upgrade", "--image", "myrepo/app:v2", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "Dry run" in result.output
    assert called["apply"] is False


def test_upgrade_happy_path_commits_syncs_and_reports_pods(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_common(tmp_path, monkeypatch)
    monkeypatch.setattr(
        upgrade_module.gitops, "check_git_preconditions", lambda cfg: _ok_preconditions()
    )
    apply_calls: dict[str, object] = {}

    def fake_apply(new_text: str, new_cfg: object, **kwargs: object) -> bool:
        apply_calls.update(kwargs)
        apply_calls["new_text"] = new_text
        return True

    monkeypatch.setattr(upgrade_module.gitops, "apply_image_change", fake_apply)
    sync_calls: dict[str, str] = {}
    monkeypatch.setattr(
        upgrade_module.argocd, "trigger_sync", lambda name: sync_calls.setdefault("sync", name)
    )
    monkeypatch.setattr(
        upgrade_module.argocd,
        "wait_for_healthy",
        lambda name, **k: argocd.ArgoAppStatus(
            name=name,
            sync_status="Synced",
            health_status="Healthy",
            revision="x",
            last_sync_time="t",
        ),
    )
    monkeypatch.setattr(
        upgrade_module.gitops, "summarize_pods", lambda ns: [("my-app-abc", "Running")]
    )

    result = runner.invoke(app, ["upgrade", "--image", "myrepo/app:v2"])
    assert result.exit_code == 0, result.output
    assert apply_calls["commit_message"] == "nexus: upgrade image to myrepo/app:v2"
    assert apply_calls["remote"] == "origin"
    assert "image: myrepo/app:v2" in apply_calls["new_text"]
    assert sync_calls["sync"] == "my-app"
    assert "my-app-abc" in result.output
    assert "upgraded to myrepo/app:v2" in result.output


def test_upgrade_wait_timeout_warns_and_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_common(tmp_path, monkeypatch)
    monkeypatch.setattr(
        upgrade_module.gitops, "check_git_preconditions", lambda cfg: _ok_preconditions()
    )
    monkeypatch.setattr(upgrade_module.gitops, "apply_image_change", lambda *a, **k: True)
    monkeypatch.setattr(upgrade_module.argocd, "trigger_sync", lambda name: None)

    def fail_wait(name: str, **k: object) -> None:
        raise NexusError(what=f"Application '{name}' did not become Synced + Healthy within 120s.")

    monkeypatch.setattr(upgrade_module.argocd, "wait_for_healthy", fail_wait)

    result = runner.invoke(app, ["upgrade", "--image", "myrepo/app:v2"])
    assert result.exit_code != 0
    assert "did not become Synced" in result.output
    assert "nexus status" in result.output


def test_upgrade_apply_no_commit_reports_noop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_common(tmp_path, monkeypatch)
    monkeypatch.setattr(
        upgrade_module.gitops, "check_git_preconditions", lambda cfg: _ok_preconditions()
    )
    monkeypatch.setattr(upgrade_module.gitops, "apply_image_change", lambda *a, **k: False)

    result = runner.invoke(app, ["upgrade", "--image", "myrepo/app:v2"])
    assert result.exit_code == 0, result.output
    assert "Nothing changed" in result.output
