"""`nexus chaos run` → pod recovery, against a real cluster (PRD §18, §7.6).

Gated behind the `chaos` marker: installing Chaos Mesh (a Helm chart) on top
of ArgoCD + monitoring is the slowest, most infra-dependent piece of the
suite, and Chaos Mesh admission-webhook readiness on Kind can be flaky (see
docs/IMPLEMENTATION-PLAN.md's webhook-race finding). Run explicitly with
``pytest -m chaos``; excluded from the default integration run.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from tests.integration.conftest import (
    CHAOS_DEPLOY_TIMEOUT,
    assert_succeeded_or_known_health_quirk,
    kubectl_json,
    run_nexus,
    wait_for_pods_running,
    write_flask_demo_config,
)


@pytest.mark.chaos
def test_chaos_run_kills_one_pod_and_recovers(scratch_repo: Path) -> None:
    app_name = f"it-chaos-{uuid.uuid4().hex[:8]}"
    write_flask_demo_config(scratch_repo, app_name=app_name, chaos=True)

    try:
        deploy_result = run_nexus(
            ["deploy", "--yes"], cwd=scratch_repo, timeout=CHAOS_DEPLOY_TIMEOUT
        )
        assert_succeeded_or_known_health_quirk(deploy_result)
        wait_for_pods_running(app_name, expected_count=2)

        before = sorted(
            p["metadata"]["name"] for p in kubectl_json("get", "pods", "-n", app_name)["items"]
        )

        chaos_result = run_nexus(["chaos", "run"], cwd=scratch_repo, timeout=90)
        assert chaos_result.returncode == 0, chaos_result.stdout
        assert "is active" in chaos_result.stdout
        assert "was killed" in chaos_result.stdout
        assert "Recovered" in chaos_result.stdout

        wait_for_pods_running(app_name, expected_count=2)
        after = sorted(
            p["metadata"]["name"] for p in kubectl_json("get", "pods", "-n", app_name)["items"]
        )
        assert before != after, "exactly one pod should have been replaced"
        assert len(set(before) & set(after)) == 1, "the other pod should be untouched"
    finally:
        run_nexus(["destroy"], cwd=scratch_repo, input_text=f"{app_name}\n", timeout=60)
