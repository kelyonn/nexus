"""Partial-failure recoverability, against a real cluster (PRD §12).

Manifests apply fine (a bad image doesn't fail `kubectl apply`), but the pod
never becomes Ready — `nexus status` must name the problem with a fix, and
the app must still be fully removable afterward. This is the real-cluster
counterpart to Week 1's manual verification step ("break the image via
kubectl set image... nexus status should show ImagePullBackOff").
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path

from tests.integration.conftest import (
    DEPLOY_TIMEOUT,
    assert_succeeded_or_known_health_quirk,
    kubectl_json,
    run_nexus,
    write_flask_demo_config,
)

BAD_IMAGE = "kelyonnnn17/nexus-app:this-tag-does-not-exist"
POD_PROBLEM_TIMEOUT = 60


def test_bad_image_is_diagnosed_and_recoverable(scratch_repo: Path) -> None:
    app_name = f"it-badimg-{uuid.uuid4().hex[:8]}"
    write_flask_demo_config(scratch_repo, app_name=app_name, image=BAD_IMAGE)

    deploy_result = run_nexus(["deploy", "--yes"], cwd=scratch_repo, timeout=DEPLOY_TIMEOUT)
    assert_succeeded_or_known_health_quirk(deploy_result)

    # Give Kubernetes time to actually attempt (and fail) the image pull.
    deadline = time.monotonic() + POD_PROBLEM_TIMEOUT
    problem_seen = False
    while time.monotonic() < deadline:
        doc = kubectl_json("get", "pods", "-n", app_name)
        for pod in doc.get("items", []):
            for cs in pod.get("status", {}).get("containerStatuses", []):
                reason = cs.get("state", {}).get("waiting", {}).get("reason")
                if reason in {"ImagePullBackOff", "ErrImagePull"}:
                    problem_seen = True
        if problem_seen:
            break
        time.sleep(3)
    assert problem_seen, "expected an ImagePullBackOff/ErrImagePull within the timeout"

    status = run_nexus(["status"], cwd=scratch_repo, timeout=30)
    # `status` reports a diagnosis, it doesn't fail — a readable pod problem
    # is a successful status *read*, not a status-command error.
    assert status.returncode == 0, status.stdout
    assert "ImagePullBackOff" in status.stdout or "ErrImagePull" in status.stdout
    assert "Fix:" in status.stdout

    # The broken app must still be fully, cleanly removable.
    destroy = run_nexus(["destroy"], cwd=scratch_repo, input_text=f"{app_name}\n", timeout=60)
    assert destroy.returncode == 0, destroy.stdout
    assert "fully removed" in destroy.stdout

    ns = kubectl_json("get", "namespace", app_name)
    assert ns == {}
