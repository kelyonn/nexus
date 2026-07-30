"""Unit tests for the pure parsing logic in tests/integration/conftest.py.

This one function is worth a fast, no-cluster-needed test of its own: it's
what decides whether a real-cluster integration test's non-zero exit is
tolerated (sync never reached Synced — expected, given scratch_repo has no
git remote) or a genuine failure (Degraded, or Synced-but-unhealthy) worth
stopping the test over. Getting this wrong in either direction is bad —
too loose and a real regression stops failing CI; too strict and every
integration run fails on infrastructure the test setup itself causes.
"""

from __future__ import annotations

import pytest

from tests.integration.conftest import _sync_never_reached


@pytest.mark.parametrize(
    "output",
    [
        "Error: did not become Synced + Healthy within 120s.\n"
        "Last observed status: sync=Unknown, health=Progressing.",
        "did not become Synced + Healthy within 120s.\n"
        "Last observed status: sync=OutOfSync, health=Missing.",
    ],
)
def test_tolerated_when_sync_never_reached_synced(output: str) -> None:
    assert _sync_never_reached(output) is True


@pytest.mark.parametrize(
    "output",
    [
        # Synced but genuinely Degraded — a real failure, not a git-remote
        # artifact of the test setup.
        "did not become Synced + Healthy within 120s.\n"
        "Last observed status: sync=Synced, health=Degraded.",
        # Synced + still Progressing at timeout: wait_for_healthy's own
        # replica-count cross-check already returns success once a
        # Synced+Progressing rollout is actually ready, so reaching this
        # timeout with that combination means it genuinely wasn't ready.
        "did not become Synced + Healthy within 120s.\n"
        "Last observed status: sync=Synced, health=Progressing.",
        # No status detail to parse at all.
        "did not become Synced + Healthy within 120s.",
        # An unrelated failure entirely.
        "Error: cluster unreachable.",
        "",
    ],
)
def test_not_tolerated_otherwise(output: str) -> None:
    assert _sync_never_reached(output) is False
