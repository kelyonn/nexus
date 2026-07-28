"""Tests for the `nexus rollback` command (PRD §7.10).

Same stubbing philosophy as test_upgrade.py: `gitops.check_git_preconditions`,
`gitops.apply_image_change`, `git.revert`/`git.push`, and `git.log_image_commits`
are stubbed here (their own correctness lives in test_git.py/test_gitops.py) so
these tests focus on `rollback`'s own orchestration — which target-selection
path runs, confirmation gating, --dry-run, and the sync/wait/report tail.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from nexus_cli.commands import rollback as rollback_module
from nexus_cli.core import argocd, git, gitops, preflight
from nexus_cli.core.output import NexusError
from nexus_cli.main import app

runner = CliRunner()

VALID_YAML = """
app:
  name: my-app
  image: myrepo/app:v2
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


def _commit(
    sha: str, short: str, *, subject: str = "nexus: upgrade image to v2"
) -> git.ImageCommit:
    return git.ImageCommit(sha=sha, short_sha=short, date="2026-07-20", subject=subject)


def _healthy_status(name: str) -> argocd.ArgoAppStatus:
    return argocd.ArgoAppStatus(
        name=name,
        sync_status="Synced",
        health_status="Healthy",
        revision="x",
        last_sync_time="t",
    )


def _setup_common(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    monkeypatch.setattr(preflight, "ensure_cluster_ready", lambda **k: None)
    monkeypatch.setattr(
        rollback_module.gitops, "check_git_preconditions", lambda cfg: _ok_preconditions()
    )
    monkeypatch.setattr(rollback_module.argocd, "trigger_sync", lambda name: None)
    monkeypatch.setattr(
        rollback_module.argocd, "wait_for_healthy", lambda name, **k: _healthy_status(name)
    )
    monkeypatch.setattr(rollback_module.gitops, "summarize_pods", lambda ns: [])


# --- --list ---


def test_rollback_list_does_not_touch_the_cluster(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    def fail_if_called(**k: object) -> None:
        raise AssertionError("preflight should not run for --list")

    monkeypatch.setattr(preflight, "ensure_cluster_ready", fail_if_called)
    monkeypatch.setattr(
        rollback_module.git, "log_image_commits", lambda: [_commit("a" * 40, "aaa")]
    )
    monkeypatch.setattr(
        rollback_module.gitops, "image_at_commit", lambda sha, **k: "myrepo/app:v2"
    )

    result = runner.invoke(app, ["rollback", "--list"])
    assert result.exit_code == 0, result.output
    assert "aaa" in result.output
    assert "myrepo/app:v2" in result.output


def test_rollback_list_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(rollback_module.git, "log_image_commits", lambda: [])

    result = runner.invoke(app, ["rollback", "--list"])
    assert result.exit_code == 0, result.output
    assert "No nexus-authored image changes" in result.output


# --- preflight / preconditions ---


def test_rollback_preflight_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)

    def fail(**k: object) -> None:
        raise NexusError(what="cluster not reachable")

    monkeypatch.setattr(preflight, "ensure_cluster_ready", fail)
    result = runner.invoke(app, ["rollback"], input="y\n")
    assert result.exit_code != 0
    assert "cluster not reachable" in result.output


def test_rollback_git_precondition_failure_surfaces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    monkeypatch.setattr(preflight, "ensure_cluster_ready", lambda **k: None)

    def fail(cfg: object) -> gitops.GitPreconditions:
        raise NexusError(what="Working tree has uncommitted changes.")

    monkeypatch.setattr(rollback_module.gitops, "check_git_preconditions", fail)
    result = runner.invoke(app, ["rollback"], input="y\n")
    assert result.exit_code != 0
    assert "uncommitted changes" in result.output


def test_rollback_branch_mismatch_decline_aborts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_common(tmp_path, monkeypatch)
    monkeypatch.setattr(
        rollback_module.gitops,
        "check_git_preconditions",
        lambda cfg: _ok_preconditions(branch_matches=False, branch="other"),
    )
    called = {"reverted": False}
    monkeypatch.setattr(
        rollback_module.git, "log_image_commits", lambda: [_commit("a" * 40, "aaa")]
    )
    monkeypatch.setattr(
        rollback_module.gitops, "image_at_commit", lambda sha, **k: "myrepo/app:v1"
    )
    monkeypatch.setattr(
        rollback_module.git, "revert", lambda sha: called.__setitem__("reverted", True)
    )

    result = runner.invoke(app, ["rollback"], input="n\n")
    assert result.exit_code != 0
    assert "Aborted" in result.output
    assert called["reverted"] is False


# --- default (no flag): git revert path ---


def test_rollback_default_no_commits_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_common(tmp_path, monkeypatch)
    monkeypatch.setattr(rollback_module.git, "log_image_commits", lambda: [])

    result = runner.invoke(app, ["rollback"], input="y\n")
    assert result.exit_code != 0
    assert "No nexus-authored image changes" in result.output


def test_rollback_default_happy_path_reverts_pushes_and_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_common(tmp_path, monkeypatch)
    commit = _commit("deadbeef" * 5, "deadbee")
    monkeypatch.setattr(rollback_module.git, "log_image_commits", lambda: [commit])

    def fake_image_at_commit(sha: str, **k: object) -> str:
        assert sha == f"{commit.sha}^"
        return "myrepo/app:v1"

    monkeypatch.setattr(rollback_module.gitops, "image_at_commit", fake_image_at_commit)

    revert_calls: dict[str, str] = {}
    monkeypatch.setattr(
        rollback_module.git, "revert", lambda sha: revert_calls.setdefault("sha", sha)
    )
    push_calls: dict[str, tuple[str, str]] = {}
    monkeypatch.setattr(
        rollback_module.git,
        "push",
        lambda remote, branch: push_calls.setdefault("push", (remote, branch)),
    )
    monkeypatch.setattr(
        rollback_module.gitops, "summarize_pods", lambda ns: [("my-app-abc", "Running")]
    )

    result = runner.invoke(app, ["rollback"], input="y\n")
    assert result.exit_code == 0, result.output
    assert revert_calls["sha"] == commit.sha
    assert push_calls["push"] == ("origin", "main")
    assert "my-app-abc" in result.output
    assert "rolled back to myrepo/app:v1" in result.output


def test_rollback_revert_failure_propagates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_common(tmp_path, monkeypatch)
    commit = _commit("a" * 40, "aaa")
    monkeypatch.setattr(rollback_module.git, "log_image_commits", lambda: [commit])
    monkeypatch.setattr(rollback_module.gitops, "image_at_commit", lambda sha, **k: "myrepo/app:v1")

    def fail_revert(sha: str) -> None:
        raise NexusError(what=f"git revert of {sha} failed.", fix="Use --to-commit instead.")

    monkeypatch.setattr(rollback_module.git, "revert", fail_revert)

    result = runner.invoke(app, ["rollback"], input="y\n")
    assert result.exit_code != 0
    assert "git revert" in result.output


def test_rollback_dry_run_does_not_revert(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_common(tmp_path, monkeypatch)
    commit = _commit("a" * 40, "aaa")
    monkeypatch.setattr(rollback_module.git, "log_image_commits", lambda: [commit])
    monkeypatch.setattr(rollback_module.gitops, "image_at_commit", lambda sha, **k: "myrepo/app:v1")
    called = {"reverted": False}
    monkeypatch.setattr(
        rollback_module.git, "revert", lambda sha: called.__setitem__("reverted", True)
    )

    result = runner.invoke(app, ["rollback", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "Dry run" in result.output
    assert called["reverted"] is False


def test_rollback_dry_run_skips_branch_mismatch_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--dry-run must never block on a confirmation, even with a branch
    mismatch. No `input=` is passed on purpose: if the branch-mismatch prompt
    fired, CliRunner would hit EOF on stdin and abort before the dry-run
    message.
    """
    _setup_common(tmp_path, monkeypatch)
    monkeypatch.setattr(
        rollback_module.gitops,
        "check_git_preconditions",
        lambda cfg: _ok_preconditions(branch_matches=False, branch="other"),
    )
    commit = _commit("a" * 40, "aaa")
    monkeypatch.setattr(rollback_module.git, "log_image_commits", lambda: [commit])
    monkeypatch.setattr(rollback_module.gitops, "image_at_commit", lambda sha, **k: "myrepo/app:v1")
    called = {"reverted": False}
    monkeypatch.setattr(
        rollback_module.git, "revert", lambda sha: called.__setitem__("reverted", True)
    )

    result = runner.invoke(app, ["rollback", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "Dry run" in result.output
    assert called["reverted"] is False


def test_rollback_bad_target_errors_before_branch_mismatch_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A doomed command (bad --to-commit sha) must fail on that, not first ask
    the user to confirm a branch mismatch for a rollback that can't happen
    anyway. No `input=` passed: if the mismatch prompt fired first, CliRunner
    would hit EOF and abort with a different message than the "Could not
    find" error this asserts on.
    """
    _setup_common(tmp_path, monkeypatch)
    monkeypatch.setattr(
        rollback_module.gitops,
        "check_git_preconditions",
        lambda cfg: _ok_preconditions(branch_matches=False, branch="other"),
    )
    monkeypatch.setattr(rollback_module.gitops, "image_at_commit", lambda sha, **k: None)

    result = runner.invoke(app, ["rollback", "--to-commit", "bogus"])
    assert result.exit_code != 0
    assert "Could not find" in result.output


# --- --to-commit path ---


def test_rollback_to_commit_bad_sha_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_common(tmp_path, monkeypatch)
    monkeypatch.setattr(rollback_module.gitops, "image_at_commit", lambda sha, **k: None)

    result = runner.invoke(app, ["rollback", "--to-commit", "bogus"], input="y\n")
    assert result.exit_code != 0
    assert "Could not find" in result.output


def test_rollback_to_commit_happy_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_common(tmp_path, monkeypatch)
    monkeypatch.setattr(
        rollback_module.gitops,
        "image_at_commit",
        lambda sha, **k: "myrepo/app:v0" if sha == "abc123" else None,
    )
    apply_calls: dict[str, object] = {}

    def fake_apply(new_text: str, new_cfg: object, **kwargs: object) -> bool:
        apply_calls.update(kwargs)
        return True

    monkeypatch.setattr(rollback_module.gitops, "apply_image_change", fake_apply)

    result = runner.invoke(app, ["rollback", "--to-commit", "abc123"], input="y\n")
    assert result.exit_code == 0, result.output
    assert apply_calls["commit_message"] == "nexus: rollback image to myrepo/app:v0"
    assert "rolled back to myrepo/app:v0" in result.output


def test_rollback_yes_flag_skips_both_confirmations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_common(tmp_path, monkeypatch)
    monkeypatch.setattr(
        rollback_module.gitops,
        "check_git_preconditions",
        lambda cfg: _ok_preconditions(branch_matches=False, branch="other"),
    )
    commit = _commit("a" * 40, "aaa")
    monkeypatch.setattr(rollback_module.git, "log_image_commits", lambda: [commit])
    monkeypatch.setattr(rollback_module.gitops, "image_at_commit", lambda sha, **k: "myrepo/app:v1")
    monkeypatch.setattr(rollback_module.git, "revert", lambda sha: None)
    monkeypatch.setattr(rollback_module.git, "push", lambda remote, branch: None)

    result = runner.invoke(app, ["rollback", "--yes"])  # no input piped at all
    assert result.exit_code == 0, result.output
