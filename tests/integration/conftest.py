"""Shared fixtures for the real-cluster integration suite (PRD §18).

These tests invoke the installed ``nexus`` console script as a subprocess
against whatever cluster the current kubectl context points at (Kind in CI,
Kind or Minikube locally) — black-box, the same way a real user runs it.

**Why `nexus deploy` is expected to time out waiting on ArgoCD here, and why
that's tolerated:** every test in this suite uses ``scratch_repo`` — a git
repo with no remote (see its own docstring). ArgoCD's ``sync`` status is a
comparison against a git remote it can reach; with none configured, `sync`
never leaves `Unknown`/`OutOfSync`, so `argocd.wait_for_healthy`'s 120s wait
always runs to its full timeout and `nexus deploy`/`upgrade`/`rollback`
exit 1 with "did not become Synced + Healthy" — even though the manifests
applied fine and the app is genuinely running. Asserting a strict exit-0 on
these commands would make the whole suite fail on a property of the test
setup, not of Nexus's own correctness. ``run_nexus`` tolerates *only* that
one specific, parsed cause (`sync` never reached `Synced`) — never a
`Degraded`/`Missing` health status, and never a `Synced`+non-`Healthy`
combination, both of which are real problems `wait_for_healthy` would
otherwise resolve on its own (see its docstring — it already cross-checks
live replica counts and returns success once a `Synced`+`Progressing`
rollout is actually ready, so that combination should not reach this
timeout at all in a healthy run; if it does, something is genuinely wrong
and this tolerance does not swallow it). Real pod/deployment state is
additionally verified directly via ``kubectl`` at every call site
(``wait_for_pods_running`` or an equivalent direct check), never inferred
from the CLI's exit code alone — this tolerance only decides whether a
non-zero exit is worth stopping the test over, not whether the test passes.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FLASK_DEMO_CONFIG = REPO_ROOT / "examples" / "flask-demo" / "nexus.yaml"

_HEALTH_QUIRK_MARKER = "did not become Synced + Healthy"
# Matches wait_for_healthy's own "Last observed status: sync=X, health=Y."
# (argocd.py) — parsed so the tolerance below can key off the actual
# reported sync status instead of just the presence of the marker string,
# which alone can't distinguish "sync never reached Synced" (expected,
# tolerated) from "sync reached Synced but health is genuinely Degraded"
# (a real failure, not tolerated).
_STATUS_DETAIL_RE = re.compile(r"Last observed status: sync=(\w+), health=(\w+)")
POD_WAIT_TIMEOUT = 120
POD_WAIT_INTERVAL = 3

# `nexus deploy`'s own worst-case runtime, not just Helm's: cold ArgoCD +
# kube-prometheus-stack installs (each up to helm.py's INSTALL_TIMEOUT=600s,
# though normally well under a minute) *plus* argocd.wait_for_healthy's own
# fixed 120s wait, which — given the documented ArgoCD health-status quirk
# (docs/IMPLEMENTATION-PLAN.md) — reliably runs to completion rather than
# returning early. A subprocess timeout smaller than install-time + 120s
# will kill a perfectly successful deploy while it's still (correctly)
# waiting, exactly as observed the first time this suite ran.
DEPLOY_TIMEOUT = 400
CHAOS_DEPLOY_TIMEOUT = DEPLOY_TIMEOUT + 150  # + a third Helm install (Chaos Mesh)


def _sync_never_reached(output: str) -> bool:
    """True only for the one cause this suite's ``scratch_repo`` setup makes
    inevitable: ``sync`` never became ``Synced`` (no reachable git remote).
    False for every other combination — including a parse failure, so an
    unrecognized message shape fails loud rather than being silently
    tolerated by accident.
    """
    if _HEALTH_QUIRK_MARKER not in output:
        return False
    match = _STATUS_DETAIL_RE.search(output)
    if not match:
        return False
    sync_status, _health_status = match.groups()
    return sync_status != "Synced"


@dataclass(frozen=True)
class NexusResult:
    returncode: int
    stdout: str
    health_quirk: bool  # True if the only failure was sync never reaching Synced


def run_nexus(
    args: list[str], *, cwd: Path, input_text: str | None = None, timeout: int = 180
) -> NexusResult:
    """Run ``nexus <args>`` as a subprocess (the real console script)."""
    result = subprocess.run(
        ["nexus", *args],
        cwd=cwd,
        input=input_text,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    output = result.stdout + result.stderr
    health_quirk = result.returncode != 0 and _sync_never_reached(output)
    return NexusResult(returncode=result.returncode, stdout=output, health_quirk=health_quirk)


def assert_succeeded_or_known_health_quirk(result: NexusResult) -> None:
    """The only acceptable non-zero exit is ``sync`` never reaching `Synced`
    (expected — see this module's docstring) — anything else, including a
    genuinely Degraded/unhealthy app, is a real failure worth stopping the
    test over. Callers should still independently verify real cluster state
    afterward (e.g. ``wait_for_pods_running``) — this only decides whether a
    non-zero exit is worth stopping the test over, not whether it passes.
    """
    if result.returncode != 0 and not result.health_quirk:
        pytest.fail(f"nexus command failed unexpectedly:\n{result.stdout}")


def kubectl_json(*args: str) -> dict:
    result = subprocess.run(
        ["kubectl", *args, "-o", "json"], capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        return {}
    return json.loads(result.stdout) if result.stdout.strip() else {}


def wait_for_pods_running(
    namespace: str, *, expected_count: int, timeout: int = POD_WAIT_TIMEOUT
) -> None:
    """Poll until ``expected_count`` pods in ``namespace`` are Running — the
    real, direct proof of rollout success, independent of ArgoCD's own
    (sometimes-lagging) health reporting.
    """
    deadline = time.monotonic() + timeout
    last_seen: list[tuple[str, str]] = []
    while time.monotonic() < deadline:
        doc = kubectl_json("get", "pods", "-n", namespace)
        items = doc.get("items", [])
        last_seen = [
            (i["metadata"]["name"], i.get("status", {}).get("phase", "Unknown")) for i in items
        ]
        running = [p for p in last_seen if p[1] == "Running"]
        if len(running) >= expected_count:
            return
        time.sleep(POD_WAIT_INTERVAL)
    pytest.fail(f"Pods in '{namespace}' never reached {expected_count} Running: {last_seen}")


@pytest.fixture(scope="session", autouse=True)
def cluster_ready() -> None:
    """Skip the whole suite (not error) if there's no reachable cluster —
    these tests are opt-in, run explicitly against Kind/Minikube, not part
    of the fast unit suite.
    """
    result = subprocess.run(["kubectl", "cluster-info"], capture_output=True, timeout=15)
    if result.returncode != 0:
        pytest.skip("No reachable Kubernetes cluster — integration tests need Kind or Minikube.")


@pytest.fixture()
def scratch_repo(tmp_path: Path) -> Path:
    """A throwaway git repo, no remote, on 'main' — deploy's git-sync step
    will soft-skip (branch mismatch against flask-demo's 'cli-platform',
    exactly as documented and observed all session), which is expected, not
    a test failure: these tests verify the app rolls out and is manageable,
    not ArgoCD's Synced status specifically (that needs a reachable git
    remote from inside the cluster, out of scope for CI — see finding #6).
    """
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    return tmp_path


def write_flask_demo_config(
    dest_dir: Path,
    *,
    app_name: str,
    image: str | None = None,
    chaos: bool | None = None,
    secrets: list[dict[str, str]] | None = None,
) -> Path:
    """Copy examples/flask-demo/nexus.yaml into a scratch dir, with a unique
    app name (so parallel/repeated test runs never collide on a namespace),
    an optional image override (bad-image partial-failure test), an optional
    chaos toggle (chaos-run integration test), and an optional app.secrets
    list (e.g. [{"name": "DB_PASSWORD", "valueEnv": "APP_DB_PASSWORD"}]) for
    the app.secrets end-to-end test.
    """
    data = yaml.safe_load(FLASK_DEMO_CONFIG.read_text())
    data["app"]["name"] = app_name
    if image:
        data["app"]["image"] = image
    if chaos is not None:
        data["platform"]["chaos"] = chaos
    if secrets is not None:
        data["app"]["secrets"] = secrets
    dest = dest_dir / "nexus.yaml"
    dest.write_text(yaml.safe_dump(data, sort_keys=False))
    return dest
