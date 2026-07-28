"""``nexus chaos`` — one-shot pod-kill experiments and the recurring schedule
(PRD §7.6, §7.7).

``chaos run`` applies a one-shot ``PodChaos`` CR built directly from the
legacy ``pod-kill.yaml`` shape (PRD §0 maps both ``pod-kill.yaml`` and
``pod-kill-schedule.yaml`` onto the single ``podchaos.yaml.j2`` *schedule*
template — the one-shot run intentionally isn't part of that declarative,
config-driven template set, since each run needs a unique name and isn't
meant to be git-synced).

``chaos schedule enable``/``disable`` manage the recurring ``Schedule`` CR
(``podchaos.yaml.j2``). Chaos Mesh has no ``spec`` field for pausing a
Schedule — pausing is done via the ``experiment.chaos-mesh.org/pause``
annotation (confirmed against https://chaos-mesh.org/docs/define-scheduling-rules/),
which also pauses any already-running experiment, unlike a plain CronJob
suspend.

Live-verified finding: Chaos Mesh's admission webhook can still be starting
up for a few seconds right after ``helm upgrade --install --wait`` reports
the release ready (its controller pods are ``Running`` before the webhook
server is actually serving) — a ``kubectl apply``/``patch`` against a
chaos-mesh resource run immediately after a fresh install can fail with
``failed calling webhook "vauth.kb.io"``, then succeed a few seconds later
with no other change. Since ``nexus chaos ...`` right after the ``nexus
deploy`` that first installs Chaos Mesh is exactly the common case, mutating
calls to chaos-mesh resources retry briefly on that specific error instead
of failing a command whose whole point is to run right after install.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable

import typer
import yaml

from nexus_cli.core import config as nexus_config
from nexus_cli.core import kubectl, output, preflight, render

CHAOS_NAMESPACE = "chaos-mesh"
_VALID_ACTIONS = {"pod-kill", "pod-failure", "container-kill"}
_PAUSE_ANNOTATION = "experiment.chaos-mesh.org/pause"

RUN_DURATION = "30s"
RECOVERY_TIMEOUT = 60
RECOVERY_POLL_INTERVAL = 2

_WEBHOOK_ERROR_MARKER = "failed calling webhook"
WEBHOOK_RETRY_TIMEOUT = 20
WEBHOOK_RETRY_INTERVAL = 2


def _with_webhook_retry(fn: Callable[[], object]) -> None:
    """Retry ``fn`` briefly if it fails with Chaos Mesh's webhook-not-ready
    error (see module docstring); any other NexusError re-raises immediately.
    """
    deadline = time.monotonic() + WEBHOOK_RETRY_TIMEOUT
    while True:
        try:
            fn()
            return
        except output.NexusError as err:
            if _WEBHOOK_ERROR_MARKER not in (err.why or "") or time.monotonic() >= deadline:
                raise
            time.sleep(WEBHOOK_RETRY_INTERVAL)


def _schedule_name(app_name: str) -> str:
    return f"{app_name}-chaos-schedule"


def _ensure_ready(config_path: str) -> nexus_config.NexusConfig:
    try:
        preflight.ensure_cluster_ready(require_helm=False)
        cfg = nexus_config.load(config_path)
    except output.NexusError as err:
        output.print_error(err)
        raise typer.Exit(code=1) from err
    if not kubectl.namespace_exists(CHAOS_NAMESPACE):
        no_chaos_mesh = output.NexusError(
            what="Chaos Mesh is not installed.",
            why="Nexus needs the Chaos Mesh controller on the cluster to run experiments.",
            fix="Set `platform.chaos: true` in nexus.yaml and run `nexus deploy`.",
        )
        output.print_error(no_chaos_mesh)
        raise typer.Exit(code=1)
    if not kubectl.namespace_exists(cfg.app.name):
        no_namespace = output.NexusError(
            what=f"Namespace '{cfg.app.name}' not found.",
            why="The app isn't deployed yet.",
            fix="Run `nexus deploy` first.",
        )
        output.print_error(no_namespace)
        raise typer.Exit(code=1)
    return cfg


def _list_pods(namespace: str) -> list[dict]:
    doc = kubectl.get_json("pods", namespace=namespace)
    items: list[dict] = doc.get("items", [])
    return items


def _pod_names(namespace: str) -> set[str]:
    return {item["metadata"]["name"] for item in _list_pods(namespace)}


def _report_recovery(
    namespace: str,
    before: set[str],
    *,
    timeout: int = RECOVERY_TIMEOUT,
    poll_interval: int = RECOVERY_POLL_INTERVAL,
) -> None:
    """Poll until the killed pod(s) are replaced and every pod is Running.

    Checking "every *currently listed* pod is Running" alone isn't enough —
    right after a kill, the replacement may not exist yet, so a smaller,
    all-Running remainder would look like recovery prematurely. Recovery
    requires both the pod count back to (at least) its pre-chaos size *and*
    every one of those pods Running.
    """
    deadline = time.monotonic() + timeout
    expected_count = len(before)
    killed: set[str] = set()
    while time.monotonic() < deadline:
        time.sleep(poll_interval)
        items = _list_pods(namespace)
        current = {item["metadata"]["name"] for item in items}
        newly_gone = before - current
        if newly_gone and not killed:
            killed = newly_gone
            for name in sorted(killed):
                output.step(f"  Pod {name} was killed.")
        all_running = bool(items) and all(
            item.get("status", {}).get("phase") == "Running" for item in items
        )
        if killed and len(items) >= expected_count and all_running:
            output.success("Recovered — all pods Running.")
            return
    output.warn("Timed out waiting to confirm recovery — check `nexus status`.")


def run(
    config_path: str = typer.Option(
        "nexus.yaml", "--config", help="Path to the nexus.yaml to read."
    ),
    kill_all: bool = typer.Option(
        False, "--kill-all", help="Kill all pods simultaneously instead of just one."
    ),
    action: str = typer.Option(
        "pod-kill", "--action", help="Chaos type: pod-kill, pod-failure, container-kill."
    ),
) -> None:
    """Trigger a one-shot PodChaos experiment against the app's pods."""
    if action not in _VALID_ACTIONS:
        err = output.NexusError(
            what=f"Unknown chaos action '{action}'.",
            why=f"Supported actions: {', '.join(sorted(_VALID_ACTIONS))}.",
            fix="Pass one of the supported actions to --action.",
        )
        output.print_error(err)
        raise typer.Exit(code=1)

    cfg = _ensure_ready(config_path)
    namespace = cfg.app.name
    mode = "all" if kill_all else "one"
    run_name = f"{namespace}-chaos-{uuid.uuid4().hex[:8]}"

    manifest = {
        "apiVersion": "chaos-mesh.org/v1alpha1",
        "kind": "PodChaos",
        "metadata": {
            "name": run_name,
            "namespace": CHAOS_NAMESPACE,
            "labels": {"app": namespace, "managed-by": "nexus"},
        },
        "spec": {
            "action": action,
            "mode": mode,
            "selector": {"namespaces": [namespace], "labelSelectors": {"app": namespace}},
            "duration": RUN_DURATION,
        },
    }

    before = _pod_names(namespace)
    text = yaml.safe_dump(manifest, sort_keys=False)
    try:
        _with_webhook_retry(lambda: kubectl.apply_manifest(text))
    except output.NexusError as err:
        output.print_error(err)
        raise typer.Exit(code=1) from err

    blast = "all pods" if kill_all else "one pod"
    output.success(f"'{run_name}' is active — {action} ({blast}).")
    _report_recovery(namespace, before)


def _patch_pause_annotation(name: str, *, paused: bool) -> None:
    value = "true" if paused else None
    patch = json.dumps({"metadata": {"annotations": {_PAUSE_ANNOTATION: value}}})
    _with_webhook_retry(
        lambda: kubectl.run(
            ["patch", "schedule", name, "-n", CHAOS_NAMESPACE, "--type", "merge", "-p", patch]
        )
    )


def _report_schedule_status(cfg: nexus_config.NexusConfig, name: str) -> None:
    doc = kubectl.get_json("schedule", namespace=CHAOS_NAMESPACE, name=name)
    annotations = doc.get("metadata", {}).get("annotations", {}) or {}
    paused = annotations.get(_PAUSE_ANNOTATION) == "true"
    state = "Suspended" if paused else "Active"
    output.step(f"Schedule: {cfg.platform.chaosSchedule} — {state}")


def schedule_enable(
    config_path: str = typer.Option(
        "nexus.yaml", "--config", help="Path to the nexus.yaml to read."
    ),
) -> None:
    """Apply the recurring PodChaos schedule, resuming it if it was suspended."""
    cfg = _ensure_ready(config_path)
    name = _schedule_name(cfg.app.name)
    try:
        text = render.render_template("podchaos", cfg)
        _with_webhook_retry(lambda: kubectl.apply_manifest(text))
        _patch_pause_annotation(name, paused=False)
    except output.NexusError as err:
        output.print_error(err)
        raise typer.Exit(code=1) from err
    output.success(f"Chaos schedule enabled for {cfg.app.name}.")
    _report_schedule_status(cfg, name)


def schedule_disable(
    config_path: str = typer.Option(
        "nexus.yaml", "--config", help="Path to the nexus.yaml to read."
    ),
) -> None:
    """Suspend the recurring PodChaos schedule (does not delete it)."""
    cfg = _ensure_ready(config_path)
    name = _schedule_name(cfg.app.name)
    try:
        kubectl.get_json("schedule", namespace=CHAOS_NAMESPACE, name=name)
    except output.NexusError as err:
        friendly = output.NexusError(
            what=f"No chaos schedule found for '{cfg.app.name}'.",
            why=str(err),
            fix="Run `nexus chaos schedule enable` first.",
        )
        output.print_error(friendly)
        raise typer.Exit(code=1) from err
    try:
        _patch_pause_annotation(name, paused=True)
    except output.NexusError as err:
        output.print_error(err)
        raise typer.Exit(code=1) from err
    output.success(f"Chaos schedule suspended for {cfg.app.name}.")
    _report_schedule_status(cfg, name)


chaos_app = typer.Typer(help="Chaos experiments: one-shot runs and the recurring schedule.")
chaos_app.command(name="run")(run)

schedule_app = typer.Typer(help="Enable or disable the recurring PodChaos schedule.")
schedule_app.command(name="enable")(schedule_enable)
schedule_app.command(name="disable")(schedule_disable)
chaos_app.add_typer(schedule_app, name="schedule")
