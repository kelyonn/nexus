"""Pod log retrieval via the ``kubernetes`` SDK (PRD §7.8, §11).

PRD §11 splits cluster access deliberately: simple calls shell out to
``kubectl``, watch/streaming calls use the Python SDK. Log reads are the
latter, so this module is the one place in ``core/`` that talks to the SDK
instead of ``core/kubectl.py``.

Returns data rather than printing it, so the same fetch backs both ``nexus
logs`` and any caller that needs logs as values (the dashboard backend).

Note the ``_preload_content=False`` call below — it works around a real
deserialization bug in ``kubernetes==36.0.3``, not a stylistic preference.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from kubernetes import client as k8s_client
from kubernetes import config as k8s_config
from kubernetes.client.exceptions import ApiException

from nexus_cli.core.output import NexusError

DEFAULT_TAIL = 50


@dataclass(frozen=True)
class PodLog:
    """One pod's log tail, or the reason it couldn't be read.

    A failure for a single pod is reported in-band rather than raised: one pod
    still in ``ContainerCreating`` shouldn't cost you the logs of every other
    pod in the app.
    """

    pod: str
    lines: list[str] = field(default_factory=list)
    error: str | None = None


def load_kube_config() -> None:
    """Load the ambient kubeconfig, or raise a what/why/fix error."""
    try:
        k8s_config.load_kube_config()
    except Exception as exc:
        raise NexusError(
            what="Could not load a Kubernetes config.",
            why=str(exc),
            fix="Check that `kubectl` works and your kubeconfig is set up.",
        ) from exc


def get_pod_logs(
    namespace: str, app_name: str, *, tail: int = DEFAULT_TAIL
) -> list[PodLog]:
    """Each matching pod's log tail, sorted by pod name.

    A snapshot, not a live follow. An empty list means no pods matched.
    """
    load_kube_config()
    api = k8s_client.CoreV1Api()
    pod_list = api.list_namespaced_pod(namespace, label_selector=f"app={app_name}")
    pod_names = sorted(pod.metadata.name for pod in pod_list.items)

    results: list[PodLog] = []
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
            results.append(PodLog(pod=pod_name, error=str(exc.reason)))
            continue
        results.append(PodLog(pod=pod_name, lines=[ln for ln in log_text.splitlines() if ln]))
    return results
