"""``nexus chaos`` — one-shot pod-kill experiments and the recurring schedule
(PRD §7.6, §7.7).

This is the terminal-facing half: option parsing, preflight, and the recovery
narration a human watches after a kill. Building and applying the experiments
themselves lives in ``core/chaos.py``, so the dashboard's chaos endpoint
(PRD §10.2) triggers the exact same experiments without going through Typer.

``chaos run`` applies a one-shot ``PodChaos``. ``chaos schedule
enable``/``disable`` manage the recurring ``Schedule`` CR
(``podchaos.yaml.j2``) via Chaos Mesh's pause annotation — see
``core/chaos.py`` for why an annotation rather than a spec field, and for the
admission-webhook race the mutating calls retry around.
"""

from __future__ import annotations

import time

import typer

from nexus_cli.core import chaos as core_chaos
from nexus_cli.core import config as nexus_config
from nexus_cli.core import kubectl, output, preflight, render

CHAOS_NAMESPACE = core_chaos.NAMESPACE

RECOVERY_TIMEOUT = 60
RECOVERY_POLL_INTERVAL = 2


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
        items = core_chaos.list_pod_items(namespace)
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
    try:
        core_chaos.validate_action(action)
    except output.NexusError as err:
        output.print_error(err)
        raise typer.Exit(code=1) from err

    cfg = _ensure_ready(config_path)
    namespace = cfg.app.name

    before = core_chaos.pod_names(namespace)
    try:
        run_name = core_chaos.run_experiment(namespace, action=action, kill_all=kill_all)
    except output.NexusError as err:
        output.print_error(err)
        raise typer.Exit(code=1) from err

    blast = "all pods" if kill_all else "one pod"
    output.success(f"'{run_name}' is active — {action} ({blast}).")
    _report_recovery(namespace, before)


def _report_schedule_status(cfg: nexus_config.NexusConfig, name: str) -> None:
    state = "Suspended" if core_chaos.is_schedule_paused(name) else "Active"
    output.step(f"Schedule: {cfg.platform.chaosSchedule} — {state}")


def schedule_enable(
    config_path: str = typer.Option(
        "nexus.yaml", "--config", help="Path to the nexus.yaml to read."
    ),
) -> None:
    """Apply the recurring PodChaos schedule, resuming it if it was suspended."""
    cfg = _ensure_ready(config_path)
    name = core_chaos.schedule_name(cfg.app.name)
    try:
        text = render.render_template("podchaos", cfg)
        core_chaos.with_webhook_retry(lambda: kubectl.apply_manifest(text))
        core_chaos.patch_pause_annotation(name, paused=False)
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
    name = core_chaos.schedule_name(cfg.app.name)
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
        core_chaos.patch_pause_annotation(name, paused=True)
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
