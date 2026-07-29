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
            )
        )
    return pods


def replica_counts(namespace: str, name: str) -> tuple[int, int]:
    """(desired, available) replica counts for the app's Deployment."""
    doc = kubectl.get_json("deployment", namespace=namespace, name=name)
    desired = doc.get("spec", {}).get("replicas", 0)
    available = doc.get("status", {}).get("availableReplicas", 0)
    return desired, available


def image_pull_fix() -> str:
    """Context-aware fix suggestion for ImagePullBackOff (PRD §7.2)."""
    context = kubectl.current_context() or ""
    if "minikube" in context.lower():
        return "Run `minikube image load <image>` to make the image visible to the cluster."
    return "Push the image to a registry the cluster can reach (Docker Hub, GHCR, ECR, etc.)."
