"""``nexus upgrade`` — bump the app's image through GitOps (PRD §7.9).

Updates ``nexus.yaml``'s ``app.image`` *and* re-renders + commits ``k8s/``
together (see ``core/gitops.py``'s module docstring for why — PRD §13 says
"only commit nexus.yaml", but that's stale: ArgoCD reconciles from ``k8s/``,
never from ``nexus.yaml`` directly, so committing only the latter would make
this command a silent no-op). Triggers an explicit ArgoCD sync rather than
waiting on its ~3-minute default poll (PRD §7.9), then waits for rollout and
reports the resulting pod status.

This is one of only two commands (with `rollback`) that write to the user's
git history — highest-care review, test against a throwaway repo.
"""

from __future__ import annotations

from pathlib import Path

import typer

from nexus_cli.core import argocd, gitops, output, preflight
from nexus_cli.core import config as nexus_config

SYNC_WAIT_TIMEOUT = 120


def upgrade(
    image: str = typer.Option(..., "--image", help="New image, e.g. myrepo/app:v2."),
    config_path: str = typer.Option(
        "nexus.yaml", "--config", help="Path to the nexus.yaml to read."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would change without committing."
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip the branch-mismatch confirmation."
    ),
) -> None:
    """Bump the app's image, commit + push through git, and roll out via ArgoCD."""
    try:
        preflight.ensure_cluster_ready(require_helm=False)
        cfg = nexus_config.load(config_path)
    except output.NexusError as err:
        output.print_error(err)
        raise typer.Exit(code=1) from err

    output.step("")
    output.step(f"Nexus Upgrade — {cfg.app.name}")
    output.step("-" * 43)
    output.step(f"Current image: {cfg.app.image}")
    output.step(f"New image:     {image}")

    if image == cfg.app.image:
        output.step("")
        output.warn("Already at that image — nothing to do.")
        return

    try:
        pre = gitops.check_git_preconditions(cfg)
    except output.NexusError as err:
        output.print_error(err)
        raise typer.Exit(code=1) from err

    current_text = Path(config_path).read_text()
    try:
        new_text, new_cfg = gitops.build_validated_config(
            current_text, image, config_path=config_path
        )
    except output.NexusError as err:
        output.print_error(err)
        raise typer.Exit(code=1) from err

    if dry_run:
        output.step("")
        output.step("Dry run — nexus.yaml and k8s/ would be updated, committed, and pushed.")
        output.step("No changes made.")
        return

    # Only prompt once we know there's real work to do and nothing else will
    # fail first (PRD says warn-and-confirm on mismatch, not block a preview
    # or a doomed command with a premature question).
    if not pre.branch_matches:
        output.warn(
            f"Current branch ('{pre.branch}') does not match platform.branch "
            f"('{cfg.platform.branch}')."
        )
        output.step("ArgoCD tracks platform.branch — committing here would desync it.")
        if not yes and not typer.confirm("Continue anyway?", default=False):
            output.warn("Aborted — nothing changed.")
            raise typer.Exit(code=1)

    committed = gitops.apply_image_change(
        new_text,
        new_cfg,
        config_path=config_path,
        remote=pre.remote,
        branch=cfg.platform.branch,
        commit_message=f"nexus: upgrade image to {image}",
    )
    if not committed:
        output.warn("Nothing changed — image was already up to date.")
        return

    output.step("")
    output.step("Syncing via ArgoCD...")
    argocd.trigger_sync(cfg.app.name)
    try:
        argocd.wait_for_healthy(cfg.app.name, timeout=SYNC_WAIT_TIMEOUT)
    except output.NexusError as err:
        output.print_error(err)
        output.step("")
        output.step("The image change was committed and pushed — check `nexus status`.")
        raise typer.Exit(code=1) from err

    output.step("")
    output.step("Pods:")
    for name, phase in gitops.summarize_pods(cfg.app.name):
        output.step(f"  {name}  {phase}")
    output.step("")
    output.success(f"{cfg.app.name} upgraded to {image}")
