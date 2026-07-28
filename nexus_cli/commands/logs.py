"""``nexus logs`` — pod logs for the app, prefixed by pod name (PRD §7.8).

Uses the ``kubernetes`` Python SDK (PRD §11: SDK for watch/streaming calls)
to fetch each matching pod's log tail — a snapshot, not a live follow.
"""

from __future__ import annotations

import typer
from kubernetes import client as k8s_client
from kubernetes import config as k8s_config
from kubernetes.client.exceptions import ApiException

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


def logs(
    config_path: str = typer.Option(
        "nexus.yaml", "--config", help="Path to the nexus.yaml to read."
    ),
    tail: int = typer.Option(50, "--tail", help="Number of lines to show per pod."),
) -> None:
    """Print each pod's log tail, prefixed with the pod name."""
    try:
        preflight.ensure_cluster_ready(require_helm=False)
        cfg = nexus_config.load(config_path)
    except output.NexusError as err:
        output.print_error(err)
        raise typer.Exit(code=1) from err

    namespace = cfg.app.name
    _load_kube_config()

    api = k8s_client.CoreV1Api()
    pod_list = api.list_namespaced_pod(namespace, label_selector=f"app={cfg.app.name}")
    pod_names = sorted(pod.metadata.name for pod in pod_list.items)

    if not pod_names:
        output.warn(f"No pods found for '{cfg.app.name}'.")
        return

    for pod_name in pod_names:
        try:
            # `_preload_content=False` avoids a kubernetes-client deserialization bug
            # where read_namespaced_pod_log() returns str(bytes) (a literal "b'...'"
            # string) instead of decoded text. The raw response's .data is real bytes.
            resp = api.read_namespaced_pod_log(
                pod_name, namespace, tail_lines=tail, _preload_content=False
            )
            log_text = resp.data.decode("utf-8", errors="replace")
        except ApiException as exc:
            output.warn(f"Could not fetch logs for {pod_name}: {exc.reason}")
            continue
        for line in log_text.splitlines():
            if line:
                output.step(f"{pod_name} | {line}")
