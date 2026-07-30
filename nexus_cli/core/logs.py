"""Pod log retrieval via the ``kubernetes`` SDK (PRD §7.8, §11).

PRD §11 splits cluster access deliberately: simple calls shell out to
``kubectl``, watch/streaming calls use the Python SDK. Log reads are the
latter, so this module is the one place in ``core/`` that talks to the SDK
instead of ``core/kubectl.py``.

``get_pod_logs`` returns data rather than printing it, so the same fetch
backs both ``nexus logs`` and any caller that needs logs as values (the
dashboard backend). ``follow_pod_logs`` is different in kind — an
indefinite, Ctrl+C-driven terminal stream, the same category as ``nexus
watch`` — so it takes a callback instead; there's no realistic non-CLI
consumer for a live-follow blocking call the way there is for a one-shot
snapshot.

Note the ``_preload_content=False`` call below — it works around a real
deserialization bug in ``kubernetes==36.0.3``, not a stylistic preference.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field

from kubernetes import client as k8s_client
from kubernetes import config as k8s_config
from kubernetes import watch as k8s_watch
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


def follow_pod_logs(
    namespace: str,
    app_name: str,
    *,
    tail: int = DEFAULT_TAIL,
    on_line: Callable[[str, str], None],
) -> list[str]:
    """Stream every matching pod's logs live until Ctrl+C.

    One thread per pod: the SDK's log-follow response is a blocking stream
    for that one pod, so following N pods concurrently needs N threads —
    same reasoning as ``nexus watch``'s single event stream needing just
    one. ``kubernetes.watch.Watch`` genuinely supports this (not just
    watching list events): it inspects the wrapped function's docstring for
    a ``follow`` parameter and, when found, yields raw log lines instead of
    trying to unmarshal them as WatchEvent JSON — verified against the
    installed ``kubernetes`` package's source before relying on it, not
    assumed from the class's list-watching examples.

    Returns the pod names being followed. Empty means nothing matched, and
    this returns immediately without blocking — callers should treat that
    the same as ``get_pod_logs()`` returning an empty list. In the normal
    (non-empty) case this call doesn't return at all until every follower
    thread's stream ends (rare — pods deleted mid-follow) or a
    ``KeyboardInterrupt`` propagates up from here (the common case, Ctrl+C;
    not caught here — see ``commands/logs.py``, which mirrors
    ``commands/watch.py``'s own top-level handling). Live-verified against
    a real cluster that a plain, unbounded ``Thread.join()`` per thread
    here really does get interrupted by a genuine Ctrl+C — a first pass at
    testing this with a background shell job (``cmd &``) suggested
    otherwise, but that was a false negative from the shell itself
    (backgrounded jobs get ``SIGINT`` set to ignored under job control,
    independent of anything this function does); re-tested with a small
    wrapper that resets ``SIGINT`` to its default disposition before exec,
    matching what a real interactive terminal actually does, and the plain
    ``join()`` stops immediately.

    ``on_line(pod_name, line)`` may be called from any of the follower
    threads — callers that print should serialize their own output (an
    unsynchronized ``print`` from multiple threads can interleave and
    garble mid-line).
    """
    load_kube_config()
    api = k8s_client.CoreV1Api()
    pod_list = api.list_namespaced_pod(namespace, label_selector=f"app={app_name}")
    pod_names = sorted(pod.metadata.name for pod in pod_list.items)
    if not pod_names:
        return []

    def _follow_one(pod_name: str) -> None:
        watcher = k8s_watch.Watch()
        try:
            for line in watcher.stream(
                api.read_namespaced_pod_log,
                name=pod_name,
                namespace=namespace,
                tail_lines=tail,
                follow=True,
            ):
                if line:
                    on_line(pod_name, line)
        except ApiException as exc:
            on_line(pod_name, f"<log stream ended: {exc.reason}>")

    threads = [
        threading.Thread(target=_follow_one, args=(pod_name,), daemon=True)
        for pod_name in pod_names
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return pod_names
