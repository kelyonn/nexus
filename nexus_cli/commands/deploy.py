"""``nexus deploy`` — install platform deps, apply manifests, sync them to
git, register with ArgoCD, verify (PRD §7.2, §8).

Never proceeds without confirmation (or ``--yes``). Safe to run repeatedly:
platform components already installed are skipped, and ``kubectl apply``
updates existing app manifests / the ArgoCD Application in place rather than
duplicating them (``helm upgrade --install`` is idempotent on its own too).

GitOps bootstrap: ArgoCD's Application tracks ``platform.repoURL`` /
``platform.branch`` at the fixed path ``k8s/`` (see the template mapping in
PRD §0). For ArgoCD to ever report the app as **Synced** (not just Healthy),
that path must actually contain the same manifests Nexus just applied
directly. So, between applying manifests and registering the Application,
this command also writes the rendered manifests to ``<cwd>/k8s/`` and
commits + pushes them (``sync_manifests_to_git``) — establishing the git
baseline ArgoCD needs on the very first deploy, not just on later
``nexus upgrade`` runs.

That git step is scoped and, deliberately, a *soft* step: it only
``git add``s the ``k8s/`` directory (so it can never sweep up unrelated
dirty files elsewhere in the user's tree), is a no-op if nothing changed
(idempotent), and — unlike every other step here — a failure in it prints a
warning and lets deployment continue rather than aborting. Rationale: a
misconfigured git remote/branch is common for a first-ever `nexus deploy`
(no repo yet, wrong branch checked out, no push access), and failing the
*entire* deploy over it would break the "app running in under 10 minutes"
promise for a first-time or purely-local/demo user. The tradeoff: on a
git-write failure, the app is still live (direct kubectl apply already
succeeded), but ArgoCD's Application will show OutOfSync/Unknown until the
user fixes their git setup and re-runs `nexus deploy` (safe — idempotent).

Live-verified: with a real git remote reachable from inside the cluster (a
`git daemon` on the host, reached via `host.minikube.internal` from a
Minikube pod), `sync_manifests_to_git` + the explicit `argocd.trigger_sync`
in `register_argocd_app` took a fresh Application from registration to
`sync: Synced` — confirming this closes the original gap (previously,
`nexus deploy` never wrote anything to the tracked repo, so ArgoCD had
nothing valid to compare against and stayed at `sync: Unknown` forever).

That same test surfaced a separate, unrelated finding worth knowing: on
ArgoCD v3.4.5, `health` can stay `Progressing` for a Deployment that
Kubernetes itself reports as fully ready (`Available: True`, N/N ready) —
observed stable for 90+ seconds and unchanged by a manual hard-refresh. This
looks like an upstream ArgoCD health-check quirk on this resource/version, not
something `sync_manifests_to_git` or this command controls. `argocd.
wait_for_healthy` now cross-checks the Deployment's own replica counts when it
sees this exact combination (Synced + Progressing) and accepts it as ready
rather than waiting the full timeout and reporting a false failure — see that
function's docstring. Chart versions are pinned below (PRD §15) specifically
so this quirk stays reproducible rather than silently shifting under a future
`helm repo update`.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

import typer

from nexus_cli.core import argocd, git, helm, kubectl, output, preflight, registry, render, secrets
from nexus_cli.core import config as nexus_config
from nexus_cli.core.config import NexusConfig

# Chart versions are pinned to what's actually been live-verified throughout
# this project (PRD §15: "Helm/ArgoCD version skew breaks install" ->
# "Mitigation: pin tested versions"). ArgoCD's app_version (v3.4.5) is the
# exact version with the health:Progressing quirk `argocd.wait_for_healthy`
# works around — pinning keeps that quirk reproducible instead of letting a
# routine `helm repo update` silently change which bugs are in play.
ARGO_RELEASE = "argocd"
ARGO_NAMESPACE = "argocd"
ARGO_REPO = ("argo", "https://argoproj.github.io/argo-helm")
ARGO_CHART = "argo/argo-cd"
ARGO_CHART_VERSION = "10.2.1"  # app_version v3.4.5

PROM_RELEASE = "kube-prom-stack"
PROM_NAMESPACE = "monitoring"
PROM_REPO = ("prometheus-community", "https://prometheus-community.github.io/helm-charts")
PROM_CHART = "prometheus-community/kube-prometheus-stack"
PROM_CHART_VERSION = "87.21.0"  # app_version v0.92.1

# Grafana sets `X-Frame-Options: DENY` by default, which silently blocks the
# dashboard's embedded metric panels (PRD §10.4). These two settings are what
# make the iframes work, so they're applied at install time rather than left as
# a manual post-install step. The `grafana\.ini` escape is required: helm
# --set treats `.` as a path separator, and that value key really does contain
# a dot (kube-prometheus-stack → grafana subchart → its `grafana.ini` map).
GRAFANA_EMBED_VALUES = {
    "grafana.grafana\\.ini.security.allow_embedding": "true",
    "grafana.grafana\\.ini.security.cookie_samesite": "lax",
}

CHAOS_RELEASE = "chaos-mesh"
CHAOS_NAMESPACE = "chaos-mesh"
CHAOS_REPO = ("chaos-mesh", "https://charts.chaos-mesh.org")
CHAOS_CHART = "chaos-mesh/chaos-mesh"
CHAOS_CHART_VERSION = "2.8.3"  # app_version 2.8.3

SYNC_WAIT_TIMEOUT = 120
MANIFESTS_DIR = "k8s"  # must match argocd-app.yaml.j2's spec.source.path


def _install_argocd() -> None:
    helm.repo_add(*ARGO_REPO)
    helm.upgrade_install(
        ARGO_RELEASE, ARGO_CHART, namespace=ARGO_NAMESPACE, chart_version=ARGO_CHART_VERSION
    )


def _install_monitoring() -> None:
    helm.repo_add(*PROM_REPO)
    helm.upgrade_install(
        PROM_RELEASE,
        PROM_CHART,
        namespace=PROM_NAMESPACE,
        values=GRAFANA_EMBED_VALUES,
        chart_version=PROM_CHART_VERSION,
    )


def _install_chaos() -> None:
    helm.repo_add(*CHAOS_REPO)
    helm.upgrade_install(
        CHAOS_RELEASE, CHAOS_CHART, namespace=CHAOS_NAMESPACE, chart_version=CHAOS_CHART_VERSION
    )


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


def apply_namespace(cfg: NexusConfig) -> None:
    """Apply just the app's Namespace, ahead of everything else that's
    namespaced to it — the Secret(s) below, then the Deployment/Service.

    Split out from ``apply_app_manifests`` (which used to apply the
    namespace as part of the same loop, ordered first only because
    ``render.template_names()`` happens to list it first) so that ordering
    is explicit and doesn't depend on dict iteration order matching what the
    Secret steps need.
    """
    kubectl.apply_manifest(render.render_template("namespace", cfg))


def apply_app_manifests(cfg: NexusConfig) -> None:
    """Apply every rendered template except the Namespace (applied earlier,
    on its own — see ``apply_namespace``) and the ArgoCD Application itself.
    """
    rendered = render.render_manifests(cfg)
    for name, text in rendered.items():
        if name in ("namespace", "argocd-app"):
            continue
        kubectl.apply_manifest(text)


def apply_registry_secret(cfg: NexusConfig) -> None:
    """Create/update the app's imagePullSecret, if ``app.registry`` is set.

    Must run *after* ``apply_namespace`` (the Secret is namespaced to the
    app) and *before* ``apply_app_manifests`` — the Deployment references
    this Secret via ``imagePullSecrets``, so creating it first avoids a
    first-deploy ImagePullBackOff race where the Deployment briefly
    references a Secret that doesn't exist yet. (Previously this ran after
    ``apply_app_manifests``, which had exactly that race — fixed alongside
    adding the equivalent ordering for ``apply_app_secret`` below, since both
    needed the same fix.) A no-op when ``app.registry`` is unset (most apps).
    """
    registry.apply_pull_secret(cfg.app)


def apply_app_secret(cfg: NexusConfig) -> None:
    """Create/update the app's Secret from ``app.secrets``, if set.

    Same ordering requirement as ``apply_registry_secret`` and the same
    reason: the Deployment references this Secret via ``secretKeyRef``. A
    no-op when ``app.secrets`` is unset (most apps).
    """
    secrets.apply_app_secret(cfg.app)


def sync_manifests_to_git(cfg: NexusConfig) -> str:
    """Write rendered app manifests to ``<cwd>/k8s/`` and commit + push them.

    Scoped to that one directory (``git add k8s/`` only) so unrelated dirty
    files elsewhere are never touched. A no-op if nothing changed since the
    last sync. Returns a short human-readable outcome string.
    """
    if not git.is_repo():
        raise output.NexusError(
            what="Current directory is not a git repository.",
            why="ArgoCD needs these manifests committed to platform.repoURL to report 'Synced'.",
            fix=(
                "Run `git init`, add your remote, and commit nexus.yaml — "
                "or point platform.repoURL at an existing repo you're inside of."
            ),
        )
    branch = git.current_branch()
    if branch != cfg.platform.branch:
        raise output.NexusError(
            what=f"Current git branch ('{branch}') does not match platform.branch "
            f"('{cfg.platform.branch}').",
            why="ArgoCD tracks platform.branch — committing here would desync it.",
            fix=(
                f"Run `git checkout {cfg.platform.branch}`, "
                "or update platform.branch in nexus.yaml to match."
            ),
        )
    remote = git.default_remote()
    if not remote:
        raise output.NexusError(
            what="No git remote is configured.",
            why="Nexus needs somewhere to push the rendered manifests for ArgoCD to track.",
            fix=f"Run `git remote add origin {cfg.platform.repoURL}`.",
        )

    manifests_dir = Path(MANIFESTS_DIR)
    manifests_dir.mkdir(exist_ok=True)
    rendered = render.render_manifests(cfg)
    for name, text in rendered.items():
        if name == "argocd-app":
            continue
        (manifests_dir / f"{name}.yaml").write_text(text)

    git.add([MANIFESTS_DIR])
    if not git.has_staged_changes():
        return "up to date — nothing to commit"

    git.commit(f"nexus: sync k8s manifests for {cfg.app.name}")
    git.push(remote, cfg.platform.branch)
    return f"pushed to {remote}/{cfg.platform.branch}"


def register_argocd_app(cfg: NexusConfig) -> None:
    rendered = render.render_manifests(cfg)
    argocd.register(rendered["argocd-app"])
    # Nudge ArgoCD to reconcile now rather than waiting on its default poll —
    # matters most right after sync_manifests_to_git just gave it fresh content.
    argocd.trigger_sync(cfg.app.name)


def _run_step(
    index: int, total: int, label: str, fn: Callable[[], object], *, critical: bool
) -> None:
    """Run one deploy step.

    Critical steps (PRD §12 partial-failure): a raised NexusError stops the
    whole deploy. Non-critical steps (just the git-sync step — see module
    docstring for why) only warn and let deploy continue. A step may return a
    short outcome string, appended to its "done" line.
    """
    output.info(f"[{index}/{total}] {label}...")
    start = time.monotonic()
    try:
        result = fn()
    except output.NexusError as err:
        elapsed = time.monotonic() - start
        if critical:
            output.print_error(err)
            output.step("")
            output.step("Deployment aborted at this step. Fix the issue above and re-run —")
            output.step("`nexus deploy` is safe to run again; earlier steps will be skipped.")
            raise typer.Exit(code=1) from err
        output.warn(f"    skipped ({elapsed:.0f}s) — ArgoCD sync stays pending until this is fixed")
        output.print_error(err)
        output.step("")
        return
    elapsed = time.monotonic() - start
    suffix = f" — {result}" if isinstance(result, str) else ""
    output.success(f"    done ({elapsed:.0f}s){suffix}")
    output.step("")


def deploy(
    config_path: str = typer.Option(
        "nexus.yaml", "--config", help="Path to the nexus.yaml to read."
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
) -> None:
    """Install missing platform components, apply manifests, sync to git, register with ArgoCD."""
    try:
        preflight.ensure_cluster_ready(require_helm=True)
        cfg = nexus_config.load(config_path)
    except output.NexusError as err:
        output.print_error(err)
        raise typer.Exit(code=1) from err

    name = cfg.app.name

    output.header(f"Nexus Deploy — {name}")

    for c in preflight.run(require_helm=True):
        output.check(c.passed, c.detail)

    output.step("")
    deps = dependency_status(cfg)
    for label, _namespace, installed in deps:
        if installed:
            output.check(True, f"{label} present → skip")
        else:
            output.check(False, f"{label} not installed → will install")

    # (label, fn, is_critical) — the git-sync step is the one non-critical entry.
    # Namespace, then any Secrets, then the rest of the manifests: both
    # Secret steps are referenced by the Deployment applied in
    # apply_app_manifests, so they must exist before it runs.
    plan: list[tuple[str, Callable[[], object], bool]] = []
    for label, namespace, installed in deps:
        if not installed:
            plan.append((f"Install {label} → namespace: {namespace}", _INSTALL_FNS[label], True))
    plan.append((f"Apply namespace → {name}", lambda: apply_namespace(cfg), True))
    if cfg.app.registry is not None:
        plan.append(
            (
                f"Create imagePullSecret → {cfg.app.registry_secret_name}",
                lambda: apply_registry_secret(cfg),
                True,
            )
        )
    if cfg.app.secrets:
        plan.append(
            (
                f"Create Secret → {cfg.app.secret_name}",
                lambda: apply_app_secret(cfg),
                True,
            )
        )
    plan.append(
        (f"Apply app manifests → namespace: {name}", lambda: apply_app_manifests(cfg), True)
    )
    plan.append(
        (
            f"Commit manifests to Git → {MANIFESTS_DIR}/",
            lambda: sync_manifests_to_git(cfg),
            False,
        )
    )
    plan.append(
        (
            f"Register ArgoCD app → tracking {cfg.platform.repoURL} @ {cfg.platform.branch}",
            lambda: register_argocd_app(cfg),
            True,
        )
    )

    output.step("")
    output.step("Deployment plan:")
    for i, (label, _fn, _critical) in enumerate(plan, start=1):
        output.step(f"  {i}. {label}")
    output.step("")

    if not yes and not typer.confirm("Proceed?", default=False):
        output.warn("Aborted — nothing changed.")
        raise typer.Exit(code=1)

    output.step("")
    total = len(plan)
    for i, (label, fn, critical) in enumerate(plan, start=1):
        short_label = label.split(" →")[0]
        _run_step(i, total, short_label, fn, critical=critical)

    output.info("Waiting for sync...")
    try:
        result = argocd.wait_for_healthy(name, timeout=SYNC_WAIT_TIMEOUT)
    except output.NexusError as err:
        output.print_error(err)
        output.step("")
        output.step("Your app's manifests were applied — check with `nexus status`.")
        raise typer.Exit(code=1) from err
    if result.health_status == "Healthy":
        output.success("Synced + Healthy")
    else:
        output.success("Synced — Deployment fully available")
        output.warn(
            f"ArgoCD itself still reports health={result.health_status} (a known "
            "ArgoCD quirk on some versions); the Deployment's own replica counts "
            "confirm it's actually ready."
        )

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
