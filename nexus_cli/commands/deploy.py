"""``nexus deploy`` — install platform deps, apply manifests, register with
ArgoCD, verify (PRD §7.2, §8).

Never proceeds without confirmation (or ``--yes``). Safe to run repeatedly:
platform components already installed are skipped, and ``kubectl apply``
updates existing app manifests / the ArgoCD Application in place rather than
duplicating them (``helm upgrade --install`` is idempotent on its own too).

Known gap (Phase 1): this command applies the rendered manifests directly
via kubectl *and* registers an ArgoCD Application pointing at the user's own
git repo/branch (template path ``k8s``). It does not commit anything to that
repo — only ``nexus upgrade`` (PRD §7.9) does that. If the repo's ``k8s/``
path doesn't already contain matching manifests, ArgoCD will report the
Application as OutOfSync (and, since ``prune: true``, may remove the
directly-applied resources on its next reconcile) until the user's repo
catches up. The app is still live immediately via the direct kubectl apply;
only ArgoCD's own view of sync state is affected until git and cluster agree.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import typer

from nexus_cli.core import argocd, helm, kubectl, output, preflight, render
from nexus_cli.core import config as nexus_config
from nexus_cli.core.config import NexusConfig

ARGO_RELEASE = "argocd"
ARGO_NAMESPACE = "argocd"
ARGO_REPO = ("argo", "https://argoproj.github.io/argo-helm")
ARGO_CHART = "argo/argo-cd"

PROM_RELEASE = "kube-prom-stack"
PROM_NAMESPACE = "monitoring"
PROM_REPO = ("prometheus-community", "https://prometheus-community.github.io/helm-charts")
PROM_CHART = "prometheus-community/kube-prometheus-stack"

CHAOS_RELEASE = "chaos-mesh"
CHAOS_NAMESPACE = "chaos-mesh"
CHAOS_REPO = ("chaos-mesh", "https://charts.chaos-mesh.org")
CHAOS_CHART = "chaos-mesh/chaos-mesh"

SYNC_WAIT_TIMEOUT = 120


def _install_argocd() -> None:
    helm.repo_add(*ARGO_REPO)
    helm.upgrade_install(ARGO_RELEASE, ARGO_CHART, namespace=ARGO_NAMESPACE)


def _install_monitoring() -> None:
    helm.repo_add(*PROM_REPO)
    helm.upgrade_install(PROM_RELEASE, PROM_CHART, namespace=PROM_NAMESPACE)


def _install_chaos() -> None:
    helm.repo_add(*CHAOS_REPO)
    helm.upgrade_install(CHAOS_RELEASE, CHAOS_CHART, namespace=CHAOS_NAMESPACE)


_INSTALL_FNS: dict[str, Callable[[], None]] = {
    "ArgoCD": _install_argocd,
    "kube-prometheus-stack": _install_monitoring,
    "Chaos Mesh": _install_chaos,
}


def dependency_status(cfg: NexusConfig) -> list[tuple[str, str, bool]]:
    """(label, namespace, already_installed) for each component this config needs."""
    deps = [("ArgoCD", ARGO_NAMESPACE, helm.release_exists(ARGO_RELEASE, ARGO_NAMESPACE))]
    if cfg.platform.monitoring:
        prom_installed = helm.release_exists(PROM_RELEASE, PROM_NAMESPACE)
        deps.append(("kube-prometheus-stack", PROM_NAMESPACE, prom_installed))
    if cfg.platform.chaos:
        chaos_installed = helm.release_exists(CHAOS_RELEASE, CHAOS_NAMESPACE)
        deps.append(("Chaos Mesh", CHAOS_NAMESPACE, chaos_installed))
    return deps


def apply_app_manifests(cfg: NexusConfig) -> None:
    """Apply every rendered template except the ArgoCD Application itself."""
    rendered = render.render_manifests(cfg)
    for name, text in rendered.items():
        if name == "argocd-app":
            continue
        kubectl.apply_manifest(text)


def register_argocd_app(cfg: NexusConfig) -> None:
    rendered = render.render_manifests(cfg)
    argocd.register(rendered["argocd-app"])


def _run_step(index: int, total: int, label: str, fn: Callable[[], None]) -> None:
    output.step(f"[{index}/{total}] {label}...")
    start = time.monotonic()
    try:
        fn()
    except output.NexusError as err:
        output.print_error(err)
        output.step("")
        output.step("Deployment aborted at this step. Fix the issue above and re-run —")
        output.step("`nexus deploy` is safe to run again; earlier steps will be skipped.")
        raise typer.Exit(code=1) from err
    elapsed = time.monotonic() - start
    output.success(f"    done ({elapsed:.0f}s)")


def deploy(
    config_path: str = typer.Option(
        "nexus.yaml", "--config", help="Path to the nexus.yaml to read."
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
) -> None:
    """Install missing platform components, apply manifests, register with ArgoCD."""
    try:
        preflight.ensure_cluster_ready(require_helm=True)
        cfg = nexus_config.load(config_path)
    except output.NexusError as err:
        output.print_error(err)
        raise typer.Exit(code=1) from err

    name = cfg.app.name

    output.step("")
    output.step(f"Nexus Deploy — {name}")
    output.step("-" * 43)

    for c in preflight.run(require_helm=True):
        glyph = "✓" if c.passed else "✗"
        output.step(f"{glyph} {c.detail}")

    deps = dependency_status(cfg)
    for label, _namespace, installed in deps:
        if installed:
            output.step(f"✓ {label} present → skip")
        else:
            output.step(f"✗ {label} not installed → will install")

    plan: list[tuple[str, Callable[[], None]]] = []
    for label, namespace, installed in deps:
        if not installed:
            plan.append((f"Install {label} → namespace: {namespace}", _INSTALL_FNS[label]))
    plan.append((f"Apply app manifests → namespace: {name}", lambda: apply_app_manifests(cfg)))
    plan.append(
        (
            f"Register ArgoCD app → tracking {cfg.platform.repoURL} @ {cfg.platform.branch}",
            lambda: register_argocd_app(cfg),
        )
    )

    output.step("")
    output.step("Deployment plan:")
    for i, (label, _fn) in enumerate(plan, start=1):
        output.step(f"  {i}. {label}")
    output.step("")

    if not yes and not typer.confirm("Proceed?", default=False):
        output.warn("Aborted — nothing changed.")
        raise typer.Exit(code=1)

    output.step("")
    total = len(plan)
    for i, (label, fn) in enumerate(plan, start=1):
        _run_step(i, total, label.split(" →")[0], fn)

    output.step("")
    output.step("Waiting for sync...")
    try:
        argocd.wait_for_healthy(name, timeout=SYNC_WAIT_TIMEOUT)
    except output.NexusError as err:
        output.print_error(err)
        output.step("")
        output.step("Your app's manifests were applied — check with `nexus status`.")
        raise typer.Exit(code=1) from err
    output.success("Synced + Healthy")

    output.step("")
    output.step("-" * 43)
    output.success(f"{name} is live")
    output.step("")
    output.step("Access your app:")
    output.step(f"  kubectl -n {name} port-forward svc/{name} 18080:80")
    output.step("  → http://127.0.0.1:18080")
    output.step("")
    output.step("Next steps:")
    output.step("  nexus status       → check deployment health")
    output.step("  nexus watch        → live pod events")
