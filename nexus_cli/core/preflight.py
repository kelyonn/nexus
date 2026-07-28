"""Preflight checks before touching the cluster (PRD §7.2).

Every command that talks to a cluster starts here: is kubectl installed, is
helm installed (deploy/destroy only), and can the current kubectl context
reach a cluster. Results are structured so callers can render them however
their command's UX requires (PRD §8's "[OK]"/"[!!]" checklist style).
"""

from __future__ import annotations

from dataclasses import dataclass

from nexus_cli.core import helm, kubectl
from nexus_cli.core.output import NexusError

FIX = {
    "kubectl": "Install it: https://kubernetes.io/docs/tasks/tools/#kubectl",
    "helm": "Install it: https://helm.sh/docs/intro/install/",
    "cluster": "Check `kubectl config current-context` and `kubectl cluster-info`.",
}


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    passed: bool
    detail: str


def check_kubectl_installed() -> PreflightCheck:
    version = kubectl.version_client()
    if version:
        return PreflightCheck("kubectl", True, f"kubectl found ({version})")
    return PreflightCheck("kubectl", False, "kubectl not found")


def check_helm_installed() -> PreflightCheck:
    version = helm.version()
    if version:
        return PreflightCheck("helm", True, f"helm found ({version})")
    return PreflightCheck("helm", False, "helm not found")


def check_cluster_reachable() -> PreflightCheck:
    context = kubectl.current_context()
    if context and kubectl.cluster_reachable():
        return PreflightCheck("cluster", True, f"Cluster reachable -> {context}")
    return PreflightCheck("cluster", False, "Cluster not reachable via current kubectl context")


def run(*, require_helm: bool = True) -> list[PreflightCheck]:
    """Run the applicable checks, in the order they should be reported."""
    checks = [check_kubectl_installed()]
    if require_helm:
        checks.append(check_helm_installed())
    checks.append(check_cluster_reachable())
    return checks


def ensure_cluster_ready(*, require_helm: bool = False) -> None:
    """Raise NexusError (what/why/fix) on the first failing check."""
    for c in run(require_helm=require_helm):
        if not c.passed:
            raise NexusError(
                what=f"{c.detail}.",
                why="Nexus needs this before it can talk to your cluster.",
                fix=FIX[c.name],
            )
