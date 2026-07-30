"""``nexus doctor`` — environment diagnostics (PRD §12, §15).

Read-only: never mutates the cluster or the user's files. Unlike other
commands, which stop at the first blocking problem, doctor runs every check
it can regardless of earlier failures, so a broken environment gets one full
report instead of one error per re-run.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import typer

from nexus_cli.core import config as nexus_config
from nexus_cli.core import git, helm, kubectl, output, preflight
from nexus_cli.core.config import NexusConfig

_PLATFORM_RELEASES = [
    ("ArgoCD", "argocd", "argocd"),
    ("kube-prometheus-stack", "kube-prom-stack", "monitoring"),
    ("Chaos Mesh", "chaos-mesh", "chaos-mesh"),
]


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    passed: bool
    detail: str
    fix: str | None = None


def _preflight_checks() -> list[DoctorCheck]:
    checks = []
    for c in preflight.run(require_helm=True):
        fix = None if c.passed else preflight.FIX[c.name]
        checks.append(DoctorCheck(c.name, c.passed, c.detail, fix))
    return checks


def _check_rbac() -> DoctorCheck:
    can_create_ns = kubectl.can_i("create", "namespaces")
    can_create_deploy = kubectl.can_i("create", "deployments", all_namespaces=True)
    if can_create_ns and can_create_deploy:
        return DoctorCheck("rbac", True, "Current context can create namespaces and deployments")
    missing = []
    if not can_create_ns:
        missing.append("create namespaces")
    if not can_create_deploy:
        missing.append("create deployments")
    return DoctorCheck(
        "rbac",
        False,
        f"Current context cannot {', '.join(missing)}",
        "Nexus needs a context with permission to create namespaces, deployments, and "
        "services. Ask your cluster admin for a role with these permissions, or "
        "`kubectl config use-context` to one that already has them.",
    )


def _check_config(config_path: str) -> tuple[DoctorCheck, NexusConfig | None]:
    p = Path(config_path)
    if not p.is_file():
        return (
            DoctorCheck(
                "nexus.yaml",
                False,
                f"No {config_path} found in this directory",
                "Run `nexus init` to create one, or cd into the directory that has it.",
            ),
            None,
        )
    try:
        cfg = nexus_config.load(config_path)
    except output.NexusError as err:
        # err.what already names the specific problem (bad YAML, malformed
        # root, or "Invalid <path>." for schema errors); err.why carries the
        # field-level detail for schema errors — worth showing, not dropping.
        detail = f"{err.what}\n{err.why}" if err.why else err.what
        return (
            DoctorCheck(
                "nexus.yaml",
                False,
                detail,
                err.fix or "Fix the issue and re-run `nexus doctor`.",
            ),
            None,
        )
    return DoctorCheck("nexus.yaml", True, f"{config_path} is valid (app: {cfg.app.name})"), cfg


def _check_git(cfg: NexusConfig) -> DoctorCheck:
    if not git.is_repo():
        return DoctorCheck(
            "git",
            False,
            "Current directory is not a git repository",
            "Run `git init` and add a remote, or cd into your app's repo.",
        )
    branch = git.current_branch()
    remote = git.default_remote()
    problems = []
    if branch != cfg.platform.branch:
        problems.append(
            f"current branch ('{branch}') != platform.branch ('{cfg.platform.branch}')"
        )
    if not remote:
        problems.append("no git remote configured")
    if problems:
        return DoctorCheck(
            "git",
            False,
            "; ".join(problems),
            f"Run `git checkout {cfg.platform.branch}` and/or "
            f"`git remote add origin {cfg.platform.repoURL}`.",
        )
    return DoctorCheck("git", True, f"git OK — branch '{branch}', remote '{remote}'")


def _check_registry(cfg: NexusConfig) -> DoctorCheck | None:
    """Only runs when app.registry is set. Checks *presence*, never prints
    values — a doctor report is exactly the kind of thing that ends up
    pasted into a bug report or a chat message, and this project never puts
    credentials in nexus.yaml in the first place (see core/registry.py); it
    shouldn't leak them into a diagnostic report either.
    """
    if cfg.app.registry is None:
        return None
    missing = [
        env_name
        for env_name in (cfg.app.registry.usernameEnv, cfg.app.registry.passwordEnv)
        if not os.environ.get(env_name)
    ]
    if missing:
        return DoctorCheck(
            "registry",
            False,
            f"Registry credential env var(s) not set: {', '.join(missing)}",
            f"Set {' and '.join(missing)} in your shell before running `nexus deploy`.",
        )
    return DoctorCheck("registry", True, "Registry credential env vars are set")


def _platform_status() -> list[tuple[str, str, bool]]:
    return [
        (label, namespace, helm.release_exists(release, namespace))
        for label, release, namespace in _PLATFORM_RELEASES
    ]


def doctor(
    config_path: str = typer.Option(
        "nexus.yaml", "--config", help="Path to the nexus.yaml to read, if present."
    ),
) -> None:
    """Diagnose the environment: tool installs, cluster access, RBAC, config, and git."""
    output.header("Nexus Doctor")

    checks = _preflight_checks()
    kubectl_check, helm_check, cluster_check = checks

    if cluster_check.passed:
        checks.append(_check_rbac())

    config_check, cfg = _check_config(config_path)
    checks.append(config_check)
    if cfg is not None:
        checks.append(_check_git(cfg))
        registry_check = _check_registry(cfg)
        if registry_check is not None:
            checks.append(registry_check)

    for c in checks:
        if c.passed:
            output.success(c.detail)
        else:
            output.warn(c.detail)
            if c.fix:
                output.step(f"    Fix: {c.fix}")

    if cluster_check.passed and helm_check.passed:
        output.step("")
        output.step("Platform components:")
        for label, namespace, installed in _platform_status():
            if installed:
                output.check(True, f"{label} installed (namespace: {namespace})")
            else:
                output.check(False, f"{label} not installed")

    output.step("")
    problems = [c for c in checks if not c.passed]
    if problems:
        output.warn(f"{len(problems)} problem(s) found — see fixes above.")
        raise typer.Exit(code=1)
    output.success("Everything looks good.")
