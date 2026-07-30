"""E2E and idempotency, against a real cluster (PRD §18).

`nexus init` isn't exercised here — it's interactive-prompt-driven and
already covered at the unit level (`tests/unit/test_init.py`); these tests
start from `examples/flask-demo/nexus.yaml` directly, which is what `init`
would have produced. Covers: deploy → status → destroy, `deploy` run twice
(idempotent, no duplicates), `destroy` run twice (clean no-op).
"""

from __future__ import annotations

import os
import time
import uuid
from pathlib import Path

from tests.integration.conftest import (
    DEPLOY_TIMEOUT,
    NexusResult,
    assert_succeeded_or_known_health_quirk,
    kubectl_json,
    run_nexus,
    wait_for_pods_running,
    write_flask_demo_config,
)


def _app_name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _deploy(scratch_repo: Path, app_name: str) -> NexusResult:
    write_flask_demo_config(scratch_repo, app_name=app_name)
    result = run_nexus(["deploy", "--yes"], cwd=scratch_repo, timeout=DEPLOY_TIMEOUT)
    assert_succeeded_or_known_health_quirk(result)
    return result


def _destroy(scratch_repo: Path, app_name: str) -> NexusResult:
    return run_nexus(["destroy"], cwd=scratch_repo, input_text=f"{app_name}\n", timeout=60)


def test_deploy_status_destroy(scratch_repo: Path) -> None:
    app_name = _app_name("it-e2e")
    try:
        _deploy(scratch_repo, app_name)
        wait_for_pods_running(app_name, expected_count=2)

        status = run_nexus(["status"], cwd=scratch_repo, timeout=30)
        assert status.returncode == 0, status.stdout
        assert app_name in status.stdout
        assert "Running" in status.stdout
    finally:
        destroy_result = _destroy(scratch_repo, app_name)
        assert destroy_result.returncode == 0, destroy_result.stdout
        assert "fully removed" in destroy_result.stdout

    ns = kubectl_json("get", "namespace", app_name)
    assert ns == {}, "namespace should be gone after destroy"


def test_deploy_is_idempotent(scratch_repo: Path) -> None:
    app_name = _app_name("it-idem")
    try:
        _deploy(scratch_repo, app_name)
        wait_for_pods_running(app_name, expected_count=2)
        pods_first = sorted(
            p["metadata"]["name"] for p in kubectl_json("get", "pods", "-n", app_name)["items"]
        )

        # Second deploy: no confirmation needed for an unchanged app, should
        # be fast and must not create duplicate Deployments/pods.
        second = _deploy(scratch_repo, app_name)
        assert "present" in second.stdout.lower() or "skip" in second.stdout.lower()

        pods_second = sorted(
            p["metadata"]["name"] for p in kubectl_json("get", "pods", "-n", app_name)["items"]
        )
        assert pods_first == pods_second, "a second deploy must not create/replace pods"

        deployments = kubectl_json("get", "deployments", "-n", app_name)
        assert len(deployments["items"]) == 1, "no duplicate Deployment objects"
    finally:
        _destroy(scratch_repo, app_name)


def test_destroy_is_idempotent(scratch_repo: Path) -> None:
    app_name = _app_name("it-destroy")
    _deploy(scratch_repo, app_name)
    wait_for_pods_running(app_name, expected_count=2)

    first = _destroy(scratch_repo, app_name)
    assert first.returncode == 0, first.stdout
    assert "fully removed" in first.stdout

    # Second destroy against an already-gone app: clean no-op, not an error.
    second = _destroy(scratch_repo, app_name)
    assert second.returncode == 0, second.stdout


def test_deploy_git_sync_soft_skips_on_branch_mismatch(scratch_repo: Path) -> None:
    """Confirms the documented soft-skip behavior (Week 1 finding #1):
    scratch_repo is on 'main', flask-demo's config says 'cli-platform' — the
    git-sync step must warn and continue, not abort the whole deploy.
    """
    app_name = _app_name("it-softskip")
    try:
        result = _deploy(scratch_repo, app_name)
        assert "does not match platform.branch" in result.stdout
        assert "skipped" in result.stdout.lower()
        # Manifests were still applied despite the soft-skip.
        wait_for_pods_running(app_name, expected_count=2)
    finally:
        _destroy(scratch_repo, app_name)


def test_deploy_with_app_secret_never_writes_the_value_to_disk(scratch_repo: Path) -> None:
    """The real, end-to-end proof of the app.secrets design (unit tests
    prove the mechanism against mocks; this proves the actual claim against
    a real cluster): the Secret exists, the pod's env resolves it, and the
    secret value appears nowhere under the scratch repo's k8s/ tree — the
    directory `nexus deploy` commits to git.
    """
    secret_value = "hunter2-integration-test-only"
    os.environ["IT_APP_DB_PASSWORD"] = secret_value
    try:
        app_name = _app_name("it-secret")
        try:
            write_flask_demo_config(
                scratch_repo,
                app_name=app_name,
                secrets=[{"name": "DB_PASSWORD", "valueEnv": "IT_APP_DB_PASSWORD"}],
            )
            result = run_nexus(["deploy", "--yes"], cwd=scratch_repo, timeout=DEPLOY_TIMEOUT)
            assert_succeeded_or_known_health_quirk(result)
            wait_for_pods_running(app_name, expected_count=2)

            secret = kubectl_json("get", "secret", f"{app_name}-secrets", "-n", app_name)
            assert secret != {}, "app.secrets Secret was not created"
            assert "DB_PASSWORD" in secret["data"]

            pods = kubectl_json("get", "pods", "-n", app_name)["items"]
            pod_name = pods[0]["metadata"]["name"]
            container = pods[0]["spec"]["containers"][0]
            env_names = {e["name"] for e in container.get("env", [])}
            assert "DB_PASSWORD" in env_names
            assert pod_name  # sanity: a real pod exists to have checked this on

            # The claim this test exists to prove: the value never reaches
            # the git-tracked k8s/ directory nexus deploy commits.
            k8s_dir = scratch_repo / "k8s"
            if k8s_dir.exists():
                for manifest in k8s_dir.glob("*.yaml"):
                    assert secret_value not in manifest.read_text()
        finally:
            _destroy(scratch_repo, app_name)
    finally:
        del os.environ["IT_APP_DB_PASSWORD"]


def test_status_reports_reasonable_speed(scratch_repo: Path) -> None:
    """PRD §12: `nexus status` returns in < 3 seconds."""
    app_name = _app_name("it-speed")
    try:
        _deploy(scratch_repo, app_name)
        wait_for_pods_running(app_name, expected_count=2)

        start = time.monotonic()
        result = run_nexus(["status"], cwd=scratch_repo, timeout=10)
        elapsed = time.monotonic() - start

        assert result.returncode == 0, result.stdout
        assert elapsed < 3, f"nexus status took {elapsed:.1f}s, want < 3s"
    finally:
        _destroy(scratch_repo, app_name)
