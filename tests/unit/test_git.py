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
