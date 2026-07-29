"""Subprocess wrapper around ``helm`` (PRD §7.2, §11).

Used to detect whether platform components (ArgoCD, kube-prometheus-stack,
Chaos Mesh) are already installed, and to install/upgrade them idempotently.
"""

from __future__ import annotations

import json
import shutil
import subprocess

from nexus_cli.core.output import NexusError

DEFAULT_TIMEOUT = 15
INSTALL_TIMEOUT = 600  # chart installs can be slow (PRD §12 first-run budget)


def is_installed() -> bool:
    return shutil.which("helm") is not None


def version() -> str | None:
    """Best-effort client version string, or None if unavailable."""
    if not is_installed():
        return None
    try:
        result = subprocess.run(
            ["helm", "version", "--short"],
            capture_output=True,
            text=True,
            timeout=DEFAULT_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def list_releases(namespace: str) -> list[dict]:
    """Parsed ``helm list -n <namespace> -o json``. Empty list if none/unreachable."""
    if not is_installed():
        raise NexusError(
            what="helm is required but not installed.",
            fix="Install it: https://helm.sh/docs/intro/install/",
        )
    result = subprocess.run(
        ["helm", "list", "-n", namespace, "-o", "json"],
        capture_output=True,
        text=True,
        timeout=DEFAULT_TIMEOUT,
        check=False,
    )
    if result.returncode != 0:
        raise NexusError(
            what=f"helm list -n {namespace} failed.",
            why=result.stderr.strip() or f"exit code {result.returncode}",
            fix="Check the error above and your cluster connection.",
        )
    releases: list[dict] = json.loads(result.stdout) if result.stdout.strip() else []
    return releases


def release_exists(name: str, namespace: str) -> bool:
    return any(r.get("name") == name for r in list_releases(namespace))


def upgrade_install(
    release: str,
    chart: str,
    *,
    namespace: str,
    create_namespace: bool = True,
    values: dict[str, str] | None = None,
    chart_version: str | None = None,
    timeout: int = INSTALL_TIMEOUT,
) -> subprocess.CompletedProcess[str]:
    """``helm upgrade --install <release> <chart> -n <namespace>``. Idempotent.

    ``chart_version`` pins the exact chart version to install (PRD §15's
    stated mitigation for Helm/ArgoCD version skew) rather than always
    resolving whatever is currently latest in the repo.
    """
    if not is_installed():
        raise NexusError(
            what="helm is required but not installed.",
            fix="Install it: https://helm.sh/docs/intro/install/",
        )
    args = ["helm", "upgrade", "--install", release, chart, "-n", namespace]
    if create_namespace:
        args.append("--create-namespace")
    if chart_version:
        args += ["--version", chart_version]
    for key, value in (values or {}).items():
        args += ["--set", f"{key}={value}"]
    args += ["--timeout", f"{timeout}s", "--wait"]
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout + 30, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise NexusError(
            what=f"helm install of {release} timed out after {timeout}s.",
            why="The chart may be slow to pull or the cluster may be under-resourced.",
            fix="Retry, or check `kubectl get pods -n " + namespace + "` for stuck pods.",
        ) from exc
    if result.returncode != 0:
        raise NexusError(
            what=f"helm install of {release} failed.",
            why=result.stderr.strip() or f"exit code {result.returncode}",
            fix="Check the error above and your cluster connection.",
        )
    return result


def repo_add(name: str, url: str) -> None:
    """``helm repo add <name> <url> && helm repo update``. Safe to call repeatedly."""
    if not is_installed():
        raise NexusError(
            what="helm is required but not installed.",
            fix="Install it: https://helm.sh/docs/intro/install/",
        )
    subprocess.run(
        ["helm", "repo", "add", name, url],
        capture_output=True,
        text=True,
        timeout=DEFAULT_TIMEOUT,
        check=False,
    )
    subprocess.run(
        ["helm", "repo", "update"],
        capture_output=True,
        text=True,
        timeout=DEFAULT_TIMEOUT,
        check=False,
    )
