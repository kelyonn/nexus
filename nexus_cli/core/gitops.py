"""GitOps orchestration helpers shared by ``nexus upgrade`` and ``nexus
rollback`` (PRD §7.9, §7.10).

**Why this exists, and the PRD inconsistency it resolves:** PRD §13 says
upgrade/rollback "only commit `nexus.yaml` changes." That's stale — the
ArgoCD Application's ``source.path`` is ``k8s`` (see
``templates/argocd-app.yaml.j2``), so ArgoCD reconciles from the *rendered
manifests* in ``k8s/``, never from ``nexus.yaml`` directly (the v1.2 GitOps
bootstrap fix — see ``deploy.py``'s module docstring). If upgrade/rollback
only touched ``nexus.yaml``, ArgoCD would never see the new image and no
rollout would ever happen. So both commands must update ``nexus.yaml`` *and*
re-render + commit ``k8s/`` together, exactly like ``deploy``'s
``sync_manifests_to_git`` does.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import ValidationError

from nexus_cli.core import git, kubectl, output, render
from nexus_cli.core.config import NexusConfig
from nexus_cli.core.output import NexusError

MANIFESTS_DIR = "k8s"  # must match argocd-app.yaml.j2's spec.source.path

_IMAGE_LINE_RE = re.compile(r"(?m)^(\s*image:\s*).*$")

# NOTE ON LAYERING: everything below raises NexusError but never touches
# typer or prints anything — interactive confirmation and error rendering
# stay in commands/upgrade.py and commands/rollback.py, which both call
# these. Keeping that split means the checks here are testable without any
# typer/CliRunner machinery (see test_gitops.py).


def set_image_in_config(text: str, new_image: str) -> str:
    """Replace ``app.image``'s value in raw ``nexus.yaml`` text, preserving
    every comment and everything else about the file's formatting.

    A regex substitution rather than a parse/re-serialize round-trip (via
    ``NexusConfig.to_yaml()``) on purpose: re-serializing would silently
    drop every comment in a file the user hand-maintains. ``image:`` appears
    exactly once in the schema (under ``app``), so the first match is
    unambiguous. The caller is responsible for re-validating the result via
    ``config.load()`` before trusting it.
    """
    new_text, count = _IMAGE_LINE_RE.subn(rf"\g<1>{new_image}", text, count=1)
    if count == 0:
        raise ValueError("no 'image:' field found in the given nexus.yaml text")
    return new_text


def image_at_commit(sha: str, *, config_path: str = "nexus.yaml", path: str = ".") -> str | None:
    """``app.image`` from ``nexus.yaml`` as of ``sha``, or None if the commit
    or file doesn't resolve, or the file at that point doesn't parse/have it.
    """
    text = git.show_file_at_commit(sha, config_path, path=path)
    if text is None:
        return None
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    image = data.get("app", {}).get("image")
    return image if isinstance(image, str) else None


def write_manifests(cfg: NexusConfig, *, manifests_dir: str = MANIFESTS_DIR) -> None:
    """Render and write every app manifest except the ArgoCD Application
    itself to ``<manifests_dir>/`` — the same rule ``deploy.sync_manifests_to_git``
    uses (the Application resource lives in ``argocd``, not synced via GitOps).
    """
    out = Path(manifests_dir)
    out.mkdir(exist_ok=True)
    rendered = render.render_manifests(cfg)
    for name, text in rendered.items():
        if name == "argocd-app":
            continue
        (out / f"{name}.yaml").write_text(text)


def summarize_pods(namespace: str) -> list[tuple[str, str]]:
    """(pod name, phase) for every pod in the app's namespace, for the
    post-rollout report.
    """
    doc = kubectl.get_json("pods", namespace=namespace)
    return [
        (item["metadata"]["name"], item.get("status", {}).get("phase", "Unknown"))
        for item in doc.get("items", [])
    ]


@dataclass(frozen=True)
class GitPreconditions:
    remote: str
    branch: str | None
    branch_matches: bool


def check_git_preconditions(cfg: NexusConfig) -> GitPreconditions:
    """PRD §7.9's pre-commit safety checks, shared by upgrade and rollback.

    Raises NexusError (what/why/fix) for not-a-repo, a dirty working tree, or
    a missing remote — those abort outright. A branch mismatch is reported
    back via ``branch_matches`` rather than raised: PRD §7.9 has the command
    *warn and ask for confirmation* here, not hard-abort, so the caller
    decides (via ``typer.confirm``) rather than this function deciding for it.
    """
    if not git.is_repo():
        raise NexusError(
            what="Current directory is not a git repository.",
            why="This command commits the image change to git so ArgoCD can roll it out.",
            fix="Run `git init` and add a remote, or cd into your app's repo.",
        )

    if not git.is_working_tree_clean():
        raise NexusError(
            what="Working tree has uncommitted changes.",
            why="This command needs a clean tree so its commit contains only the image change.",
            fix="Run `git stash` or `git commit` your changes, then retry.",
        )

    branch = git.current_branch()
    remote = git.default_remote()
    if not remote:
        raise NexusError(
            what="No git remote is configured.",
            why="This command needs somewhere to push the image-change commit.",
            fix=f"Run `git remote add origin {cfg.platform.repoURL}`.",
        )

    return GitPreconditions(
        remote=remote, branch=branch, branch_matches=branch == cfg.platform.branch
    )


def build_validated_config(
    current_text: str, new_image: str, *, config_path: str = "nexus.yaml"
) -> tuple[str, NexusConfig]:
    """Build the candidate nexus.yaml text with the image changed, and fully
    validate it — without writing anything to disk. Raises NexusError on a
    malformed image string, bad YAML, or a schema violation, so a bad
    ``--image``/target commit fails before anything is touched.
    """
    try:
        new_text = set_image_in_config(current_text, new_image)
    except ValueError as exc:
        raise NexusError(
            what=f"Could not update the image in {config_path}.", why=str(exc)
        ) from exc

    try:
        data = yaml.safe_load(new_text)
        new_cfg = NexusConfig.model_validate(data)
    except yaml.YAMLError as exc:
        raise NexusError(
            what=f"{config_path} is not valid YAML after the image update.", why=str(exc)
        ) from exc
    except ValidationError as exc:
        raise output.from_validation_error(exc, source=config_path) from exc

    return new_text, new_cfg


def apply_image_change(
    new_text: str,
    new_cfg: NexusConfig,
    *,
    config_path: str,
    remote: str,
    branch: str,
    commit_message: str,
) -> bool:
    """Write ``nexus.yaml`` + re-rendered ``k8s/``, then git add/commit/push.

    Returns True if a commit was actually made, False if nothing had changed
    to stage (e.g. the target image matched what was already committed).
    """
    Path(config_path).write_text(new_text)
    write_manifests(new_cfg)
    git.add([config_path, MANIFESTS_DIR])
    if not git.has_staged_changes():
        return False
    git.commit(commit_message)
    git.push(remote, branch)
    return True
