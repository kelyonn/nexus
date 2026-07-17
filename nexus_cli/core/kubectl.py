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


def delete(
    resource: str,
    name: str,
    *,
    namespace: str | None = None,
    ignore_not_found: bool = True,
) -> subprocess.CompletedProcess[str]:
    """``kubectl delete <resource> <name> [-n ns]``."""
    args = ["delete", resource, name]
    if namespace:
        args += ["-n", namespace]
    if ignore_not_found:
        args.append("--ignore-not-found=true")
    return run(args, timeout=APPLY_TIMEOUT)


def namespace_exists(name: str) -> bool:
    result = _run_raw(["get", "namespace", name], timeout=DEFAULT_TIMEOUT)
    return result.returncode == 0
