"""Subprocess wrapper around ``git`` (PRD §7.9's safety checks, applied here
and reused by the Week 2 `upgrade`/`rollback` commands).

Used by `nexus deploy` to sync rendered manifests into the user's own repo so
ArgoCD's Application — which tracks that repo/branch/path — has something
valid to reconcile against (see deploy.py's module docstring for why).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

from nexus_cli.core.output import NexusError

DEFAULT_TIMEOUT = 15
PUSH_TIMEOUT = 60

# Matches both "nexus: upgrade image to <tag>" and "nexus: rollback image to
# <tag>" commits, *and* `git revert`'s auto-generated 'Revert "nexus: ..."'
# messages (no leading '^' anchor) — a revert-of-an-upgrade is itself a real
# image-change event and must be discoverable by `--list` and re-revertible
# by a second `rollback`, exactly like an upgrade commit is.
_IMAGE_COMMIT_GREP = "nexus:.*image to "


def _run(
    args: list[str], *, timeout: int = DEFAULT_TIMEOUT, check: bool = True
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            ["git", *args], capture_output=True, text=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise NexusError(
            what=f"git {' '.join(args)} timed out after {timeout}s.",
            fix="Check your network connection and git remote access, then retry.",
        ) from exc
    except FileNotFoundError as exc:
        raise NexusError(
            what="git is required but not installed.",
            fix="Install it: https://git-scm.com/downloads",
        ) from exc
    if check and result.returncode != 0:
        raise NexusError(
            what=f"git {' '.join(args)} failed.",
            why=result.stderr.strip() or f"exit code {result.returncode}",
            fix="Check the error above.",
        )
    return result


def is_repo(path: str = ".") -> bool:
    result = _run(["-C", path, "rev-parse", "--is-inside-work-tree"], check=False)
    return result.returncode == 0 and result.stdout.strip() == "true"


def current_branch(path: str = ".") -> str | None:
    """The current branch name, or None if not on a named branch.

    Uses ``symbolic-ref`` rather than ``rev-parse --abbrev-ref HEAD``: the
    latter needs to resolve HEAD to a commit, so it fails (misreporting
    "None") on a brand-new repo with no commits yet — an "unborn" branch,
    which is a very plausible first-run state. ``symbolic-ref`` reads what
    branch HEAD points at directly, without needing a commit to exist, and
    still correctly fails (returns None) in a detached-HEAD state.
    """
    result = _run(["-C", path, "symbolic-ref", "--short", "HEAD"], check=False)
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def default_remote(path: str = ".") -> str | None:
    """The remote to push to: 'origin' if present, else the first configured one."""
    result = _run(["-C", path, "remote"], check=False)
    if result.returncode != 0:
        return None
    remotes = result.stdout.split()
    if not remotes:
        return None
    return "origin" if "origin" in remotes else remotes[0]


def add(paths: list[str], *, path: str = ".") -> None:
    _run(["-C", path, "add", *paths])


def has_staged_changes(path: str = ".") -> bool:
    result = _run(["-C", path, "diff", "--cached", "--quiet"], check=False)
    return result.returncode != 0  # non-zero => there ARE staged differences


def commit(message: str, *, path: str = ".") -> None:
    _run(["-C", path, "commit", "-m", message])


def push(remote: str, branch: str, *, path: str = ".") -> None:
    _run(["-C", path, "push", remote, branch], timeout=PUSH_TIMEOUT)


def is_working_tree_clean(path: str = ".") -> bool:
    """True if there are no uncommitted changes (tracked or staged)."""
    result = _run(["-C", path, "status", "--porcelain"], check=False)
    return result.returncode == 0 and result.stdout.strip() == ""


def revert(sha: str, *, path: str = ".") -> None:
    """``git revert --no-edit <sha>``.

    On conflict, runs ``git revert --abort`` first so the working tree is
    left clean rather than mid-revert, then raises — safer to fail loudly
    than to leave the user's repo in a half-finished state.
    """
    result = _run(["-C", path, "revert", "--no-edit", sha], check=False)
    if result.returncode != 0:
        _run(["-C", path, "revert", "--abort"], check=False)
        raise NexusError(
            what=f"git revert of {sha} failed.",
            why=result.stderr.strip() or f"exit code {result.returncode}",
            fix="Use `--to-commit <sha>` to restore a specific version instead.",
        )


def show_file_at_commit(sha: str, filepath: str, *, path: str = ".") -> str | None:
    """Contents of ``filepath`` as of ``sha``, or None if it doesn't resolve."""
    result = _run(["-C", path, "show", f"{sha}:{filepath}"], check=False)
    if result.returncode != 0:
        return None
    return result.stdout


@dataclass(frozen=True)
class ImageCommit:
    sha: str
    short_sha: str
    date: str
    subject: str


def log_image_commits(path: str = ".") -> list[ImageCommit]:
    """Nexus-authored image-change commits (upgrades, rollbacks, and reverts
    of either), newest first. See ``_IMAGE_COMMIT_GREP`` for why the match
    isn't anchored to a single exact prefix.
    """
    result = _run(
        [
            "-C",
            path,
            "log",
            "--extended-regexp",
            f"--grep={_IMAGE_COMMIT_GREP}",
            "--format=%H%x1f%h%x1f%aI%x1f%s",
        ],
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return []
    commits = []
    for line in result.stdout.strip().splitlines():
        parts = line.split("\x1f")
        if len(parts) != 4:
            continue
        sha, short_sha, date, subject = parts
        commits.append(ImageCommit(sha=sha, short_sha=short_sha, date=date, subject=subject))
    return commits
