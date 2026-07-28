"""Chaos Mesh experiment construction and application (PRD §7.6, §7.7).

The logic here is deliberately free of any CLI concern — no printing, no
``typer.Exit``, no blocking recovery poll — so both ``nexus chaos`` and the
dashboard's chaos-trigger endpoint (PRD §10.2) can drive the same experiments.
Progress reporting and recovery narration stay in ``commands/chaos.py``, which
is the only place that knows it's talking to a terminal.

One-shot ``PodChaos`` runs are built directly from the legacy
``pod-kill.yaml`` shape rather than from a template: PRD §0 maps both
``pod-kill.yaml`` and ``pod-kill-schedule.yaml`` onto the single
``podchaos.yaml.j2`` *schedule* template, and a one-shot run needs a unique
name per run and isn't meant to be git-synced.

Live-verified finding: Chaos Mesh's admission webhook can still be starting up
for a few seconds after ``helm upgrade --install --wait`` reports the release
ready (its controller pods reach ``Running`` before the webhook server is
actually serving) — a ``kubectl apply``/``patch`` against a chaos-mesh
resource run immediately after a fresh install can fail with ``failed calling
webhook "vauth.kb.io"``, then succeed seconds later with no other change.
Since running chaos right after the ``nexus deploy`` that first installs Chaos
Mesh is exactly the common case, the mutating calls here retry briefly on that
specific error instead of failing a command whose whole point is to run right
after install.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from typing import Any

import yaml

from nexus_cli.core import kubectl
from nexus_cli.core.output import NexusError

NAMESPACE = "chaos-mesh"
VALID_ACTIONS = frozenset({"pod-kill", "pod-failure", "container-kill"})
PAUSE_ANNOTATION = "experiment.chaos-mesh.org/pause"

RUN_DURATION = "30s"

_WEBHOOK_ERROR_MARKER = "failed calling webhook"
WEBHOOK_RETRY_TIMEOUT = 20
WEBHOOK_RETRY_INTERVAL = 2


def with_webhook_retry(fn: Callable[[], object]) -> None:
    """Retry ``fn`` briefly if it fails with Chaos Mesh's webhook-not-ready
    error (see module docstring); any other NexusError re-raises immediately.
    """
    deadline = time.monotonic() + WEBHOOK_RETRY_TIMEOUT
    while True:
        try:
            fn()
            return
        except NexusError as err:
            if _WEBHOOK_ERROR_MARKER not in (err.why or "") or time.monotonic() >= deadline:
                raise
            time.sleep(WEBHOOK_RETRY_INTERVAL)


def schedule_name(app_name: str) -> str:
    return f"{app_name}-chaos-schedule"


def list_pod_items(namespace: str) -> list[dict]:
    """Raw pod documents in the app's namespace."""
    doc = kubectl.get_json("pods", namespace=namespace)
    items: list[dict] = doc.get("items", [])
    return items


def pod_names(namespace: str) -> set[str]:
    return {item["metadata"]["name"] for item in list_pod_items(namespace)}


def validate_action(action: str) -> None:
    """Raise a what/why/fix error for an unsupported chaos action."""
    if action not in VALID_ACTIONS:
        raise NexusError(
            what=f"Unknown chaos action '{action}'.",
            why=f"Supported actions: {', '.join(sorted(VALID_ACTIONS))}.",
            fix="Pass one of the supported actions to --action.",
        )


def build_experiment(
    app_name: str, *, action: str, kill_all: bool, run_name: str
) -> dict[str, Any]:
    """The one-shot ``PodChaos`` document for a single run."""
    return {
        "apiVersion": "chaos-mesh.org/v1alpha1",
        "kind": "PodChaos",
        "metadata": {
            "name": run_name,
            "namespace": NAMESPACE,
            "labels": {"app": app_name, "managed-by": "nexus"},
        },
        "spec": {
            "action": action,
            "mode": "all" if kill_all else "one",
            "selector": {"namespaces": [app_name], "labelSelectors": {"app": app_name}},
            "duration": RUN_DURATION,
        },
    }


def run_experiment(app_name: str, *, action: str = "pod-kill", kill_all: bool = False) -> str:
    """Apply a one-shot PodChaos experiment; returns the generated run name.

    Returns as soon as the experiment is accepted by the cluster — observing
    the kill and the recovery that follows is the caller's job.
    """
    validate_action(action)
    run_name = f"{app_name}-chaos-{uuid.uuid4().hex[:8]}"
    manifest = build_experiment(app_name, action=action, kill_all=kill_all, run_name=run_name)
    text = yaml.safe_dump(manifest, sort_keys=False)
    with_webhook_retry(lambda: kubectl.apply_manifest(text))
    return run_name


def patch_pause_annotation(name: str, *, paused: bool) -> None:
    """Pause or resume a Schedule.

    Chaos Mesh has no ``spec`` field for pausing a Schedule — pausing is done
    via the ``experiment.chaos-mesh.org/pause`` annotation (confirmed against
    https://chaos-mesh.org/docs/define-scheduling-rules/), which also pauses
    any already-running experiment, unlike a plain CronJob suspend.
    """
    value = "true" if paused else None
    patch = json.dumps({"metadata": {"annotations": {PAUSE_ANNOTATION: value}}})
    with_webhook_retry(
        lambda: kubectl.run(
            ["patch", "schedule", name, "-n", NAMESPACE, "--type", "merge", "-p", patch]
        )
    )


def is_schedule_paused(name: str) -> bool:
    """True if the Schedule carries the pause annotation."""
    doc = kubectl.get_json("schedule", namespace=NAMESPACE, name=name)
    annotations = doc.get("metadata", {}).get("annotations", {}) or {}
    return bool(annotations.get(PAUSE_ANNOTATION) == "true")
