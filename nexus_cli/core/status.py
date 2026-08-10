"""Deployment health data — replica counts, pod status, image-pull fixes
(PRD §7.3).

Pure data, no printing: this is what both ``nexus status`` and the
dashboard's Overview/App Detail views (PRD §10.1, §10.2) read from. The
CLI-facing narration (what to print, in what order) lives in
``commands/status.py``.
"""

from __future__ import annotations

from dataclasses import dataclass

from nexus_cli.core import kubectl

IMAGE_PULL_REASONS = {"ImagePullBackOff", "ErrImagePull"}
CRASH_REASONS = {"CrashLoopBackOff"}


@dataclass(frozen=True)
class PodInfo:
    name: str
    phase: str
    restarts: int
    problem: str | None
    created_at: str | None = None  # RFC3339, straight from the pod's creationTimestamp


def _pod_problem(pod: dict) -> str | None:
    for cs in pod.get("status", {}).get("containerStatuses", []):
        reason = cs.get("state", {}).get("waiting", {}).get("reason")
        if reason in IMAGE_PULL_REASONS or reason in CRASH_REASONS:
            return str(reason)
    return None


def _pod_restarts(pod: dict) -> int:
    statuses = pod.get("status", {}).get("containerStatuses", [])
    return sum(cs.get("restartCount", 0) for cs in statuses)


def list_pods(namespace: str) -> list[PodInfo]:
    """Pods in the app's namespace (one app per namespace — no selector needed)."""
    doc = kubectl.get_json("pods", namespace=namespace)
    pods = []
    for item in doc.get("items", []):
        pods.append(
            PodInfo(
                name=item["metadata"]["name"],
                phase=item.get("status", {}).get("phase", "Unknown"),
                restarts=_pod_restarts(item),
                problem=_pod_problem(item),
                created_at=item.get("metadata", {}).get("creationTimestamp"),
            )
        )
    return pods


def replica_counts(namespace: str, name: str) -> tuple[int, int]:
    """(desired, available) replica counts for the app's Deployment."""
    doc = kubectl.get_json("deployment", namespace=namespace, name=name)
    desired = doc.get("spec", {}).get("replicas", 0)
    available = doc.get("status", {}).get("availableReplicas", 0)
    return desired, available


def rollout_complete(namespace: str, name: str) -> bool:
    """True only once the Deployment's *current* rollout has fully replaced
    old replicas.

    Unlike ``replica_counts``, also requires ``updatedReplicas`` to meet the
    desired count — during a rolling update to a broken image, the *old*
    ReplicaSet's still-healthy pods can satisfy ``availableReplicas >=
    desired`` on their own while a new bad pod sits in ImagePullBackOff/
    ErrImageNeverPull, which would otherwise read as "ready".
    """
    doc = kubectl.get_json("deployment", namespace=namespace, name=name)
    desired = doc.get("spec", {}).get("replicas", 0)
    doc_status = doc.get("status", {})
    available = doc_status.get("availableReplicas", 0)
    updated = doc_status.get("updatedReplicas", 0)
    return desired > 0 and available >= desired and updated >= desired


def image_pull_fix(pull_policy: str = "Always") -> str:
    """Context-aware fix suggestion for ImagePullBackOff (PRD §7.2).

    ``minikube image load`` only helps if the kubelet is actually willing to
    use the locally-loaded image — under ``imagePullPolicy: Always`` (the
    config default), it always re-checks the registry regardless of what's
    already loaded, so the fix would silently do nothing. Callers should pass
    the app's real ``app.imagePullPolicy`` so the advice matches what will
    actually work.
    """
    context = kubectl.current_context() or ""
    if "minikube" in context.lower():
        if pull_policy == "Always":
            return (
                "Run `minikube image load <image>`, then set "
                "`app.imagePullPolicy: IfNotPresent` in nexus.yaml and re-deploy — "
                "under the default `Always`, the kubelet re-checks the registry "
                "regardless of what's loaded locally, so the load alone won't help."
            )
        return "Run `minikube image load <image>` to make the image visible to the cluster."
    return "Push the image to a registry the cluster can reach (Docker Hub, GHCR, ECR, etc.)."
