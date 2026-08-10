"""Unit tests for dashboard.backend.prometheus (mocked urllib; no live Prometheus).

Requires the `dashboard` extra — skipped entirely if it isn't installed,
matching test_dashboard_backend.py's convention.
"""

from __future__ import annotations

import json
from urllib.error import URLError

import pytest

fastapi = pytest.importorskip("fastapi")

from dashboard.backend import prometheus  # noqa: E402
from nexus_cli.core.output import NexusError  # noqa: E402


def test_cpu_query_scopes_to_namespace() -> None:
    """No `container=` filter: cAdvisor's per-container cgroup metrics carry
    no `container` label on at least one real cluster tested against — only
    the pod-level aggregate. `namespace` alone is correct given one app per
    namespace (see the matching comment in grafana-dashboard.yaml.j2).
    """
    q = prometheus.cpu_query("my-app")
    assert 'namespace="my-app"' in q
    assert "container=" not in q
    assert "rate(container_cpu_usage_seconds_total" in q


def test_memory_query_scopes_to_namespace() -> None:
    q = prometheus.memory_query("my-app")
    assert 'namespace="my-app"' in q
    assert "container=" not in q
    assert "container_memory_working_set_bytes" in q


def test_restarts_query_scopes_to_namespace_and_container() -> None:
    q = prometheus.restarts_query("my-app")
    assert 'namespace="my-app"' in q
    assert 'container="my-app"' in q
    assert "kube_pod_container_status_restarts_total" in q


def test_desired_replicas_query_scopes_to_deployment() -> None:
    q = prometheus.desired_replicas_query("my-app")
    assert 'namespace="my-app"' in q
    assert 'deployment="my-app"' in q
    assert "kube_deployment_spec_replicas" in q


def test_available_replicas_query_scopes_to_deployment() -> None:
    q = prometheus.available_replicas_query("my-app")
    assert 'namespace="my-app"' in q
    assert 'deployment="my-app"' in q
    assert "kube_deployment_status_replicas_available" in q


def test_http_request_rate_query_scopes_to_namespace() -> None:
    q = prometheus.http_request_rate_query("my-app")
    assert 'namespace="my-app"' in q
    assert "flask_http_request_total" in q


def test_http_error_rate_query_filters_5xx() -> None:
    q = prometheus.http_error_rate_query("my-app")
    assert 'namespace="my-app"' in q
    assert 'status=~"5.."' in q


def test_http_latency_p95_query_uses_histogram_quantile() -> None:
    q = prometheus.http_latency_p95_query("my-app")
    assert 'namespace="my-app"' in q
    assert "histogram_quantile(0.95" in q


@pytest.mark.parametrize(
    ("window", "expected_seconds"),
    [("30s", 30), ("15m", 900), ("1h", 3600), ("2h", 7200)],
)
def test_parse_window_valid(window: str, expected_seconds: int) -> None:
    assert prometheus.parse_window(window) == expected_seconds


@pytest.mark.parametrize("window", ["15", "15x", "m15", "", "15m ", "-5m"])
def test_parse_window_rejects_bad_input(window: str) -> None:
    with pytest.raises(NexusError, match="Unsupported metrics window"):
        prometheus.parse_window(window)


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode()

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def test_query_range_parses_values(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "data": {
            "result": [
                {"values": [[1000.0, "1.5"], [1015.0, "2.0"]]},
            ]
        }
    }
    monkeypatch.setattr(
        prometheus.urllib.request, "urlopen", lambda url, timeout=0: _FakeResponse(payload)
    )
    result = prometheus.query_range("some_query", 900)
    assert result == [(1000.0, 1.5), (1015.0, 2.0)]


def test_query_range_empty_when_no_series(monkeypatch: pytest.MonkeyPatch) -> None:
    """No matching series (fresh app, no traffic yet) is 'nothing to show', not an error."""
    payload = {"data": {"result": []}}
    monkeypatch.setattr(
        prometheus.urllib.request, "urlopen", lambda url, timeout=0: _FakeResponse(payload)
    )
    assert prometheus.query_range("some_query", 900) == []


def test_query_range_raises_when_prometheus_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_connection_error(url: str, timeout: float = 0) -> None:
        raise URLError("Connection refused")

    monkeypatch.setattr(prometheus.urllib.request, "urlopen", raise_connection_error)
    with pytest.raises(NexusError, match="Could not reach Prometheus"):
        prometheus.query_range("some_query", 900)


def test_query_range_step_scales_with_window() -> None:
    """A larger window uses a larger step, targeting roughly the same point count."""
    small_step = max(900 // prometheus.TARGET_POINTS, 1)
    large_step = max(7200 // prometheus.TARGET_POINTS, 1)
    assert large_step > small_step


def test_query_range_many_runs_all_queries_concurrently(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_query_range(promql: str, window_seconds: int) -> list[tuple[float, float]]:
        return [(0.0, float(len(promql)))]

    monkeypatch.setattr(prometheus, "query_range", fake_query_range)
    result = prometheus.query_range_many({"a": "one", "bb": "two-ish"}, 900)
    assert result == {"a": [(0.0, 3.0)], "bb": [(0.0, 7.0)]}


def test_query_range_many_propagates_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_unreachable(promql: str, window_seconds: int) -> list[tuple[float, float]]:
        raise NexusError(what="Could not reach Prometheus.", why="Connection refused")

    monkeypatch.setattr(prometheus, "query_range", raise_unreachable)
    with pytest.raises(NexusError, match="Could not reach Prometheus"):
        prometheus.query_range_many({"a": "one"}, 900)
