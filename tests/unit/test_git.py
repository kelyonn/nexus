"""Unit tests for nexus_cli.core.git (mocked subprocess; no real repo).

A dedicated section at the bottom uses a *real* git repo (no mocking) for
``current_branch`` specifically — a mock can't catch "used the wrong git
subcommand" bugs, which is exactly how the unborn-branch bug this guards
against was found (a real user hit it on a freshly `git init`'d repo).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from nexus_cli.core import git
from nexus_cli.core.output import NexusError


class _FakeCompleted:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_is_repo_true(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        git.subprocess, "run", lambda *a, **k: _FakeCompleted(returncode=0, stdout="true\n")
    )
    assert git.is_repo() is True


def test_is_repo_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(git.subprocess, "run", lambda *a, **k: _FakeCompleted(returncode=128))
    assert git.is_repo() is False


def test_current_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        git.subprocess, "run", lambda *a, **k: _FakeCompleted(returncode=0, stdout="main\n")
    )
    assert git.current_branch() == "main"


def test_current_branch_none_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(git.subprocess, "run", lambda *a, **k: _FakeCompleted(returncode=128))
    assert git.current_branch() is None


def test_default_remote_prefers_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        git.subprocess,
        "run",
        lambda *a, **k: _FakeCompleted(returncode=0, stdout="upstream\norigin\n"),
    )
    assert git.default_remote() == "origin"


def test_default_remote_falls_back_to_first(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        git.subprocess, "run", lambda *a, **k: _FakeCompleted(returncode=0, stdout="upstream\n")
    )
    assert git.default_remote() == "upstream"


def test_default_remote_none_when_no_remotes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        git.subprocess, "run", lambda *a, **k: _FakeCompleted(returncode=0, stdout="")
    )
    assert git.default_remote() is None


def test_add_builds_correct_args(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, list[str]] = {}

    def fake_run(args: list[str], **kwargs: object) -> _FakeCompleted:
        captured["args"] = args
        return _FakeCompleted(returncode=0)

    monkeypatch.setattr(git.subprocess, "run", fake_run)
    git.add(["k8s"])
    assert captured["args"] == ["git", "-C", ".", "add", "k8s"]


def test_has_staged_changes_true(monkeypatch: pytest.MonkeyPatch) -> None:
    # `git diff --cached --quiet` exits non-zero when there ARE differences
    monkeypatch.setattr(git.subprocess, "run", lambda *a, **k: _FakeCompleted(returncode=1))
    assert git.has_staged_changes() is True


def test_has_staged_changes_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(git.subprocess, "run", lambda *a, **k: _FakeCompleted(returncode=0))
    assert git.has_staged_changes() is False


def test_commit_success(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, list[str]] = {}

    def fake_run(args: list[str], **kwargs: object) -> _FakeCompleted:
        captured["args"] = args
        return _FakeCompleted(returncode=0)

    monkeypatch.setattr(git.subprocess, "run", fake_run)
    git.commit("nexus: sync k8s manifests for my-app")
    assert captured["args"] == [
        "git",
        "-C",
        ".",
        "commit",
        "-m",
        "nexus: sync k8s manifests for my-app",
    ]


def test_commit_failure_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        git.subprocess,
        "run",
        lambda *a, **k: _FakeCompleted(returncode=1, stderr="nothing to commit"),
    )
    with pytest.raises(NexusError) as exc_info:
        git.commit("msg")
    assert "nothing to commit" in exc_info.value.why


def test_push_success(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, list[str]] = {}

    def fake_run(args: list[str], **kwargs: object) -> _FakeCompleted:
        captured["args"] = args
        return _FakeCompleted(returncode=0)

    monkeypatch.setattr(git.subprocess, "run", fake_run)
    git.push("origin", "main")
    assert captured["args"] == ["git", "-C", ".", "push", "origin", "main"]


def test_push_failure_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        git.subprocess,
        "run",
        lambda *a, **k: _FakeCompleted(returncode=1, stderr="rejected: non-fast-forward"),
    )
    with pytest.raises(NexusError) as exc_info:
        git.push("origin", "main")
    assert "rejected" in exc_info.value.why


def test_is_working_tree_clean_true(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        git.subprocess, "run", lambda *a, **k: _FakeCompleted(returncode=0, stdout="")
    )
    assert git.is_working_tree_clean() is True


def test_is_working_tree_clean_false_when_dirty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        git.subprocess,
        "run",
        lambda *a, **k: _FakeCompleted(returncode=0, stdout=" M nexus.yaml\n"),
    )
    assert git.is_working_tree_clean() is False


def test_revert_success(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, list[str]] = {}

    def fake_run(args: list[str], **kwargs: object) -> _FakeCompleted:
        captured["args"] = args
        return _FakeCompleted(returncode=0)

    monkeypatch.setattr(git.subprocess, "run", fake_run)
    git.revert("abc123")
    assert captured["args"] == ["git", "-C", ".", "revert", "--no-edit", "abc123"]


def test_revert_conflict_aborts_and_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(args: list[str], **kwargs: object) -> _FakeCompleted:
        calls.append(args)
        if "--abort" in args:
            return _FakeCompleted(returncode=0)
        return _FakeCompleted(returncode=1, stderr="CONFLICT (content): Merge conflict")

    monkeypatch.setattr(git.subprocess, "run", fake_run)
    with pytest.raises(NexusError) as exc_info:
        git.revert("abc123")
    assert "--to-commit" in exc_info.value.fix
    # both the failed revert attempt and the abort must have run
    assert any("revert" in c and "--no-edit" in c for c in calls)
    assert any("--abort" in c for c in calls)


def test_show_file_at_commit_returns_content(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        git.subprocess,
        "run",
        lambda *a, **k: _FakeCompleted(returncode=0, stdout="app:\n  image: v1\n"),
    )
    assert git.show_file_at_commit("abc123", "nexus.yaml") == "app:\n  image: v1\n"


def test_show_file_at_commit_returns_none_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        git.subprocess,
        "run",
        lambda *a, **k: _FakeCompleted(returncode=128, stderr="fatal: bad object"),
    )
    assert git.show_file_at_commit("bogus", "nexus.yaml") is None


def test_log_image_commits_parses_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    stdout = (
        "aaa111\x1faaa\x1f2026-07-20T10:00:00+00:00\x1fnexus: upgrade image to v2\n"
        'bbb222\x1fbbb\x1f2026-07-19T10:00:00+00:00\x1fRevert "nexus: upgrade image to v1"\n'
    )
    monkeypatch.setattr(
        git.subprocess, "run", lambda *a, **k: _FakeCompleted(returncode=0, stdout=stdout)
    )
    commits = git.log_image_commits()
    assert len(commits) == 2
    assert commits[0] == git.ImageCommit(
        sha="aaa111", short_sha="aaa", date="2026-07-20T10:00:00+00:00",
        subject="nexus: upgrade image to v2",
    )
    assert commits[1].subject == 'Revert "nexus: upgrade image to v1"'


def test_log_image_commits_empty_when_none_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        git.subprocess, "run", lambda *a, **k: _FakeCompleted(returncode=0, stdout="")
    )
    assert git.log_image_commits() == []


def test_timeout_raises_nexus_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_timeout(*a: object, **k: object) -> None:
        raise subprocess.TimeoutExpired(cmd="git", timeout=15)

    monkeypatch.setattr(git.subprocess, "run", raise_timeout)
    with pytest.raises(NexusError) as exc_info:
        git.commit("msg")
    assert "timed out" in exc_info.value.what


def test_git_not_installed_raises_nexus_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_not_found(*a: object, **k: object) -> None:
        raise FileNotFoundError("git")

    monkeypatch.setattr(git.subprocess, "run", raise_not_found)
    with pytest.raises(NexusError) as exc_info:
        git.commit("msg")
    assert "not installed" in exc_info.value.what


# --- current_branch against a REAL repo (no mocking) ---


def _real_init(path: Path, *, branch: str = "main") -> None:
    subprocess.run(["git", "init", "-b", branch, str(path)], capture_output=True, check=True)
    # Give the throwaway repo its own identity. Not cosmetic: `git.revert()`
    # *creates* a commit, so without an identity it fails outright on any
    # machine with no global git config — e.g. a CI runner, which is exactly
    # where this first showed up. Configuring it here also matches reality
    # (a real user's repo always has one) and keeps these tests hermetic
    # instead of silently depending on the developer's global git config.
    for key, value in (("user.email", "t@t.local"), ("user.name", "t")):
        subprocess.run(
            ["git", "-C", str(path), "config", key, value], capture_output=True, check=True
        )


def test_current_branch_real_repo_with_no_commits_yet(tmp_path: Path) -> None:
    """The exact bug scenario: `git init`, no commit made yet ('unborn' branch)."""
    _real_init(tmp_path, branch="main")
    assert git.current_branch(str(tmp_path)) == "main"


def test_current_branch_real_repo_after_a_commit(tmp_path: Path) -> None:
    _real_init(tmp_path, branch="main")
    (tmp_path / "f.txt").write_text("x")
    subprocess.run(["git", "-C", str(tmp_path), "add", "f.txt"], capture_output=True, check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.email=t@t.local",
            "-c",
            "user.name=t",
            "commit",
            "-m",
            "x",
        ],
        capture_output=True,
        check=True,
    )
    assert git.current_branch(str(tmp_path)) == "main"


def test_current_branch_real_repo_custom_branch_name_no_commits(tmp_path: Path) -> None:
    _real_init(tmp_path, branch="cli-platform")
    assert git.current_branch(str(tmp_path)) == "cli-platform"


def test_current_branch_none_outside_any_repo(tmp_path: Path) -> None:
    # tmp_path is just an empty directory, never `git init`'d
    assert git.current_branch(str(tmp_path)) is None


# --- revert / show_file_at_commit / log_image_commits against a REAL repo ---
# (a mock can't catch "used the wrong git plumbing" bugs — same rationale as
# the current_branch tests above; these three are the riskiest new additions,
# since `nexus rollback` depends on them being exactly right.)


def _real_commit(path: Path, message: str) -> str:
    """Stage everything and commit; returns the new commit's full sha."""
    subprocess.run(["git", "-C", str(path), "add", "-A"], capture_output=True, check=True)
    subprocess.run(
        [
            "git", "-C", str(path),
            "-c", "user.email=t@t.local", "-c", "user.name=t",
            "commit", "-m", message,
        ],
        capture_output=True,
        check=True,
    )
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def test_is_working_tree_clean_real_repo(tmp_path: Path) -> None:
    _real_init(tmp_path)
    (tmp_path / "nexus.yaml").write_text("app:\n  image: v1\n")
    _real_commit(tmp_path, "init")
    assert git.is_working_tree_clean(str(tmp_path)) is True

    (tmp_path / "nexus.yaml").write_text("app:\n  image: v2\n")
    assert git.is_working_tree_clean(str(tmp_path)) is False


def test_show_file_at_commit_real_repo(tmp_path: Path) -> None:
    _real_init(tmp_path)
    (tmp_path / "nexus.yaml").write_text("app:\n  image: v1\n")
    sha = _real_commit(tmp_path, "init")
    assert git.show_file_at_commit(sha, "nexus.yaml", path=str(tmp_path)) == "app:\n  image: v1\n"
    assert git.show_file_at_commit(sha, "does-not-exist.yaml", path=str(tmp_path)) is None


def test_revert_real_repo_restores_previous_content(tmp_path: Path) -> None:
    _real_init(tmp_path)
    (tmp_path / "nexus.yaml").write_text("app:\n  image: v1\n")
    _real_commit(tmp_path, "init")
    (tmp_path / "nexus.yaml").write_text("app:\n  image: v2\n")
    upgrade_sha = _real_commit(tmp_path, "nexus: upgrade image to v2")

    git.revert(upgrade_sha, path=str(tmp_path))

    assert (tmp_path / "nexus.yaml").read_text() == "app:\n  image: v1\n"
    assert git.is_working_tree_clean(str(tmp_path)) is True


def test_log_image_commits_real_repo_finds_upgrade_and_its_revert(tmp_path: Path) -> None:
    _real_init(tmp_path)
    (tmp_path / "nexus.yaml").write_text("app:\n  image: v1\n")
    _real_commit(tmp_path, "init")  # not an image-change commit — must be excluded
    (tmp_path / "nexus.yaml").write_text("app:\n  image: v2\n")
    upgrade_sha = _real_commit(tmp_path, "nexus: upgrade image to v2")
    git.revert(upgrade_sha, path=str(tmp_path))

    commits = git.log_image_commits(str(tmp_path))
    assert len(commits) == 2
    # newest first: the revert, then the original upgrade
    assert commits[0].subject.startswith('Revert "nexus: upgrade image to v2"')
    assert commits[1].sha == upgrade_sha
    assert commits[1].subject == "nexus: upgrade image to v2"
