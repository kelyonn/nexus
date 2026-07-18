"""Subprocess wrapper around ``git`` (PRD §7.9's safety checks, applied here
and reused by the Week 2 `upgrade`/`rollback` commands).

Used by `nexus deploy` to sync rendered manifests into the user's own repo so
ArgoCD's Application — which tracks that repo/branch/path — has something
valid to reconcile against (see deploy.py's module docstring for why).
"""

from __future__ import annotations

import subprocess

from nexus_cli.core.output import NexusError

DEFAULT_TIMEOUT = 15
PUSH_TIMEOUT = 60


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
    result = _run(["-C", path, "rev-parse", "--abbrev-ref", "HEAD"], check=False)
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
