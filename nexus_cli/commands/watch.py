"""``nexus watch`` — stream pod events in real time (PRD §7.4, §11).

Uses the ``kubernetes`` Python SDK's watch stream rather than plain kubectl
subprocess calls (PRD §11: SDK for watch/streaming, subprocess for simple
get/apply calls).
"""

from __future__ import annotations

from datetime import datetime

import typer
from kubernetes import client as k8s_client
from kubernetes import config as k8s_config
from kubernetes import watch as k8s_watch

from nexus_cli.core import config as nexus_config
from nexus_cli.core import output, preflight


def _load_kube_config() -> None:
    try:
        k8s_config.load_kube_config()
    except Exception as exc:
        err = output.NexusError(
            what="Could not load a Kubernetes config.",
            why=str(exc),
            fix="Check that `kubectl` works and your kubeconfig is set up.",
        )
        output.print_error(err)
        raise typer.Exit(code=1) from exc


def watch(
    config_path: str = typer.Option(
        "nexus.yaml", "--config", help="Path to the nexus.yaml to read."
    ),
) -> None:
    """Stream pod lifecycle events for the app's namespace until Ctrl+C."""
    try:
        preflight.ensure_cluster_ready(require_helm=False)
        cfg = nexus_config.load(config_path)
    except output.NexusError as err:
        output.print_error(err)
        raise typer.Exit(code=1) from err

    namespace = cfg.app.name
    _load_kube_config()

    api = k8s_client.CoreV1Api()
    watcher = k8s_watch.Watch()
    output.step(f"Watching pods in namespace '{namespace}' — Ctrl+C to stop.")
    try:
        for event in watcher.stream(api.list_namespaced_pod, namespace=namespace):
            pod = event["object"]
            phase = pod.status.phase if pod.status else "Unknown"
            timestamp = datetime.now().strftime("%H:%M:%S")
            output.step(f"[{timestamp}] Pod {pod.metadata.name} → {phase}")
    except KeyboardInterrupt:
        watcher.stop()
        output.step("")
        output.step("Stopped watching.")
