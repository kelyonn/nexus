"""Subprocess wrapper around ``kubectl`` (PRD §7.2, §11).

Every simple cluster call (get, apply, delete, cluster/context checks) goes
through here so timeouts and error translation live in one place. Streaming
calls (``nexus watch``, ``nexus logs``) use the ``kubernetes`` Python SDK
instead — see PRD §11.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any

from nexus_cli.core.output import NexusError

DEFAULT_TIMEOUT = 15
APPLY_TIMEOUT = 60

_NOT_INSTALLED = NexusError(
    what="kubectl is required but not installed.",
    fix="Install it: https://kubernetes.io/docs/tasks/tools/#kubectl",
)


def is_installed() -> bool:
    return shutil.which("kubectl") is not None


def _run_raw(
    args: list[str], *, timeout: int, input_text: str | None = None
) -> subprocess.CompletedProcess[str]:
    if not is_installed():
        raise _NOT_INSTALLED
    try:
        return subprocess.run(
            ["kubectl", *args],
            input=input_text,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise NexusError(
            what=f"kubectl {' '.join(args)} timed out after {timeout}s.",
            why="The cluster may be unreachable or overloaded.",
            fix="Check `kubectl cluster-info` and your network connection, then retry.",
        ) from exc


def run(
    args: list[str],
    *,
    timeout: int = DEFAULT_TIMEOUT,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run ``kubectl <args>``, raising NexusError (what/why/fix) on failure."""
    result = _run_raw(args, timeout=timeout)
    if check and result.returncode != 0:
        raise NexusError(
            what=f"kubectl {' '.join(args)} failed.",
            why=result.stderr.strip() or f"exit code {result.returncode}",
            fix="Check the error above and your cluster connection.",
        )
    return result


def version_client() -> str | None:
    """Best-effort client version string, or None if unavailable."""
    if not is_installed():
        return None
    result = _run_raw(["version", "--client", "-o", "json"], timeout=DEFAULT_TIMEOUT)
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
        version: str | None = data.get("clientVersion", {}).get("gitVersion")
        return version
    except (json.JSONDecodeError, AttributeError):
        return None


def current_context() -> str | None:
    """The active kubectl context name, or None if unset/unavailable."""
    if not is_installed():
        return None
    result = _run_raw(["config", "current-context"], timeout=DEFAULT_TIMEOUT)
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def cluster_reachable() -> bool:
    """True if the current context can list nodes."""
    if not is_installed():
        return False
    result = _run_raw(["get", "nodes"], timeout=DEFAULT_TIMEOUT)
    return result.returncode == 0


def get_json(
    resource: str,
    *,
    namespace: str | None = None,
    name: str | None = None,
    all_namespaces: bool = False,
) -> Any:
    """``kubectl get <resource> [name] [-n ns | -A] -o json``, parsed."""
    args = ["get", resource]
    if name:
        args.append(name)
    if all_namespaces:
        args.append("-A")
    elif namespace:
        args += ["-n", namespace]
    args += ["-o", "json"]
    result = run(args)
    return json.loads(result.stdout)


def apply_manifest(text: str) -> subprocess.CompletedProcess[str]:
    """``kubectl apply -f -`` with YAML piped via stdin. Namespace comes from the manifest."""
    result = _run_raw(["apply", "-f", "-"], timeout=APPLY_TIMEOUT, input_text=text)
    if result.returncode != 0:
        raise NexusError(
            what="kubectl apply failed.",
            why=result.stderr.strip() or f"exit code {result.returncode}",
            fix="Check the manifest and your cluster connection, then retry.",
        )
    return result


_MISSING_RESOURCE_TYPE_MARKERS = (
    "doesn't have a resource type",
    "the server could not find the requested resource",
)


def is_missing_resource_type(stderr: str) -> bool:
    """True if a kubectl error means the *kind* isn't known to the cluster.

    Distinct from "that object doesn't exist": this is the CRD itself not being
    installed — e.g. asking for an ArgoCD ``Application`` on a cluster where
    ArgoCD was never installed. Callers usually want to treat it as "there are
    none of these" rather than as a failure.
    """
    return any(m in stderr.lower() for m in _MISSING_RESOURCE_TYPE_MARKERS)


def is_not_found(stderr: str) -> bool:
    """True if a kubectl error means *this object* doesn't exist.

    The complement of :func:`is_missing_resource_type`: the kind is known, the
    named object (or its namespace) just isn't there — e.g. asking for a
    Deployment before ``nexus deploy`` has created it. Callers usually want to
    treat this as an ordinary "nothing yet" state, while still surfacing every
    *other* failure (RBAC denied, cluster unreachable) as a real problem.
    """
    lowered = stderr.lower()
    return "notfound" in lowered.replace(" ", "") or "not found" in lowered


def delete(
    resource: str,
    name: str,
    *,
    namespace: str | None = None,
    ignore_not_found: bool = True,
) -> subprocess.CompletedProcess[str]:
    """``kubectl delete <resource> <name> [-n ns]``.

    With ``ignore_not_found`` (default), treats "already gone" as success in
    both senses: the object doesn't exist (``--ignore-not-found``), or the
    resource type/CRD itself isn't installed (e.g. deleting an ArgoCD
    Application on a cluster where ArgoCD was never installed) — a case
    ``--ignore-not-found`` alone doesn't cover. Needed for `nexus destroy`
    to stay idempotent regardless of *why* a resource isn't there.
    """
    args = ["delete", resource, name]
    if namespace:
        args += ["-n", namespace]
    if ignore_not_found:
        args.append("--ignore-not-found=true")
    result = run(args, timeout=APPLY_TIMEOUT, check=False)
    if result.returncode != 0:
        already_gone = is_missing_resource_type(result.stderr)
        if not (ignore_not_found and already_gone):
            raise NexusError(
                what=f"kubectl delete {resource} {name} failed.",
                why=result.stderr.strip() or f"exit code {result.returncode}",
                fix="Check the error above and your cluster connection.",
            )
    return result


def namespace_exists(name: str) -> bool:
    result = _run_raw(["get", "namespace", name], timeout=DEFAULT_TIMEOUT)
    return result.returncode == 0


def resource_exists(resource: str, name: str, *, namespace: str) -> bool:
    """Whether a specific named resource exists — e.g. the dashboard checking
    for an app's ServiceMonitor (PRD §10.4) to know if it was ever configured,
    without needing to read the app's own nexus.yaml.
    """
    result = _run_raw(["get", resource, name, "-n", namespace], timeout=DEFAULT_TIMEOUT)
    return result.returncode == 0


def can_i(verb: str, resource: str, *, all_namespaces: bool = False) -> bool:
    """``kubectl auth can-i <verb> <resource> [-A]`` — True if the current
    context is allowed. A "no" is a legitimate answer (exit code 1), not an
    error; only kubectl itself being missing raises (via ``_run_raw``).
    """
    args = ["auth", "can-i", verb, resource]
    if all_namespaces:
        args.append("-A")
    result = _run_raw(args, timeout=DEFAULT_TIMEOUT)
    return result.returncode == 0 and result.stdout.strip().lower() == "yes"
