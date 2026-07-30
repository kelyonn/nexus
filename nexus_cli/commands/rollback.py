"""``nexus rollback`` — undo the most recent (or a specific) image change,
GitOps-correctly (PRD §7.10).

**Why git, not ArgoCD:** with ArgoCD auto-sync + self-heal enabled, an
in-place "roll back to ArgoCD revision N" gets immediately undone, because
self-heal drives the cluster back to git HEAD. So rollback operates through
git — the source of truth — the same way `upgrade` does (see
`core/gitops.py`'s module docstring for why that means `k8s/`, not just
`nexus.yaml`, despite what PRD §13 says).

Two ways to pick a target:
- Default (no flag): `git revert` of the most recent nexus-authored image
  commit. Reverting is exactly why self-heal can't undo this — HEAD itself
  now holds the old image, so self-heal reinforces it.
- `--to-commit <sha>`: restore the exact `nexus.yaml` state from that commit,
  via the same write+commit path `upgrade` uses (not a revert, since the
  target may be arbitrarily far back).

This is one of only two commands (with `upgrade`) that write to the user's
git history — highest-care review, test against a throwaway repo.
"""

from __future__ import annotations

from pathlib import Path

import typer

from nexus_cli.core import argocd, git, gitops, output, preflight
from nexus_cli.core import config as nexus_config
from nexus_cli.core.config import NexusConfig

SYNC_WAIT_TIMEOUT = 120


def _report_rollout(cfg: NexusConfig) -> None:
    """Shared tail for both rollback paths: sync, wait, report pods."""
    output.step("")
    output.step("Syncing via ArgoCD...")
    argocd.trigger_sync(cfg.app.name)
    try:
        result = argocd.wait_for_healthy(cfg.app.name, timeout=SYNC_WAIT_TIMEOUT)
    except output.NexusError as err:
        output.print_error(err)
        output.step("")
        output.step("The rollback was committed and pushed — check `nexus status`.")
        raise typer.Exit(code=1) from err
    if result.health_status != "Healthy":
        output.warn(
            f"ArgoCD itself still reports health={result.health_status} (a known "
            "ArgoCD quirk on some versions); the Deployment's own replica counts "
            "confirm it's actually ready."
        )

    output.step("")
    output.step("Pods:")
    for name, phase in gitops.summarize_pods(cfg.app.name):
        output.step(f"  {name}  {phase}")


def _list_image_commits() -> None:
    commits = git.log_image_commits()
    if not commits:
        output.step("No nexus-authored image changes found in this repo.")
        return
    output.step("")
    output.step("Recent image changes:")
    for c in commits:
        image = gitops.image_at_commit(c.sha) or "?"
        output.step(f"  {c.short_sha}  {c.date}  {image:<30}  {c.subject}")


def _check_preconditions(cfg: NexusConfig) -> gitops.GitPreconditions:
    try:
        return gitops.check_git_preconditions(cfg)
    except output.NexusError as err:
        output.print_error(err)
        raise typer.Exit(code=1) from err


def _confirm_branch_mismatch(pre: gitops.GitPreconditions, cfg: NexusConfig, *, yes: bool) -> None:
    if pre.branch_matches:
        return
    output.step("")
    output.warn(
        f"Current branch ('{pre.branch}') does not match platform.branch "
        f"('{cfg.platform.branch}')."
    )
    output.step("ArgoCD tracks platform.branch — committing here would desync it.")
    if not yes and not typer.confirm("Continue anyway?", default=False):
        output.warn("Aborted — nothing changed.")
        raise typer.Exit(code=1)


def rollback(
    to_commit: str | None = typer.Option(
        None, "--to-commit", help="Restore the nexus.yaml image from this commit."
    ),
    list_commits: bool = typer.Option(
        False, "--list", help="Show recent nexus-authored image changes."
    ),
    config_path: str = typer.Option(
        "nexus.yaml", "--config", help="Path to the nexus.yaml to read."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would change without committing."
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip the branch-mismatch and rollback confirmations."
    ),
) -> None:
    """Roll back the app's image through git — revert the last change, or
    restore the state from a specific commit with --to-commit.
    """
    if list_commits:
        _list_image_commits()
        return

    try:
        preflight.ensure_cluster_ready(require_helm=False)
        cfg = nexus_config.load(config_path)
    except output.NexusError as err:
        output.print_error(err)
        raise typer.Exit(code=1) from err

    pre = _check_preconditions(cfg)

    target_sha: str | None = None
    if to_commit:
        target_image = gitops.image_at_commit(to_commit, config_path=config_path)
        if target_image is None:
            not_found = output.NexusError(
                what=f"Could not find {config_path} at commit '{to_commit}'.",
                why="The commit may not exist, or that path didn't exist there yet.",
                fix="Run `nexus rollback --list` to see valid commits.",
            )
            output.print_error(not_found)
            raise typer.Exit(code=1)
    else:
        commits = git.log_image_commits()
        if not commits:
            no_commits = output.NexusError(
                what="No nexus-authored image changes to roll back.",
                fix="Run `nexus upgrade --image ...` first, or use `--to-commit <sha>`.",
            )
            output.print_error(no_commits)
            raise typer.Exit(code=1)
        target_sha = commits[0].sha
        target_image = gitops.image_at_commit(f"{target_sha}^", config_path=config_path)
        if target_image is None:
            no_parent_image = output.NexusError(
                what=f"Could not determine the pre-rollback image at {target_sha}^.",
                fix="Use `--to-commit <sha>` to restore a specific version instead.",
            )
            output.print_error(no_parent_image)
            raise typer.Exit(code=1)

    output.header(f"Nexus Rollback — {cfg.app.name}")
    output.step(f"Current image: {cfg.app.image}")
    output.step(f"Target image:  {target_image}")

    if dry_run:
        output.step("")
        output.step("Dry run — nexus.yaml and k8s/ would be restored, committed, and pushed.")
        output.step("No changes made.")
        return

    # Only prompt once we know there's a real target and nothing else will
    # fail first (a doomed command — bad sha, no commits — shouldn't ask a
    # premature question about the branch first).
    _confirm_branch_mismatch(pre, cfg, yes=yes)

    if not yes and not typer.confirm(f"Roll back to {target_image}?", default=False):
        output.warn("Aborted — nothing changed.")
        raise typer.Exit(code=1)

    if target_sha is None:  # --to-commit path: write + re-render + commit
        current_text = Path(config_path).read_text()
        try:
            new_text, new_cfg = gitops.build_validated_config(
                current_text, target_image, config_path=config_path
            )
        except output.NexusError as err:
            output.print_error(err)
            raise typer.Exit(code=1) from err
        committed = gitops.apply_image_change(
            new_text,
            new_cfg,
            config_path=config_path,
            remote=pre.remote,
            branch=cfg.platform.branch,
            commit_message=f"nexus: rollback image to {target_image}",
        )
        if not committed:
            output.warn("Nothing changed — image was already at that state.")
            return
    else:  # default path: git revert restores nexus.yaml + k8s/ together
        try:
            git.revert(target_sha)
        except output.NexusError as err:
            output.print_error(err)
            raise typer.Exit(code=1) from err
        git.push(pre.remote, cfg.platform.branch)

    _report_rollout(cfg)
    output.step("")
    output.success(f"{cfg.app.name} rolled back to {target_image}")
