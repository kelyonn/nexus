"""Shared fixtures for the real-cluster integration suite (PRD §18).

These tests invoke the installed ``nexus`` console script as a subprocess
against whatever cluster the current kubectl context points at (Kind in CI,
Kind or Minikube locally) — black-box, the same way a real user runs it.

**The ArgoCD health-status quirk (documented in docs/IMPLEMENTATION-PLAN.md,
Week 1 finding #3 and Week 2 finding #6):** on the ArgoCD version this repo's
`nexus deploy` installs, `health` can stay `Progressing` long after the
Deployment is actually ready, so `wait_for_healthy`'s 120s wait — and
therefore `nexus deploy`/`upgrade`/`rollback` themselves — can exit 1 even
when the rollout genuinely succeeded. Asserting a strict exit-0 on these
commands would make the whole suite flake on infrastructure timing, not on
Nexus's own correctness. ``run_nexus`` tolerates exactly that one known
failure signature and nothing else; real pod/deployment state is always
verified directly via ``kubectl``, never inferred from the CLI's exit code
alone.
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FLASK_DEMO_CONFIG = REPO_ROOT / "examples" / "flask-demo" / "nexus.yaml"

_HEALTH_QUIRK_MARKER = "did not become Synced + Healthy"
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


@dataclass(frozen=True)
class NexusResult:
    returncode: int
    stdout: str
    health_quirk: bool  # True if the only failure was the known ArgoCD lag


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
    health_quirk = result.returncode != 0 and _HEALTH_QUIRK_MARKER in output
    return NexusResult(returncode=result.returncode, stdout=output, health_quirk=health_quirk)


def assert_succeeded_or_known_health_quirk(result: NexusResult) -> None:
    """The only acceptable non-zero exit is the documented ArgoCD lag —
    anything else is a real failure worth stopping the test over.
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
