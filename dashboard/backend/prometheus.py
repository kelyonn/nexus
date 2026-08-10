"""Prometheus query proxy for the App Detail sparklines (PRD §10.2).

Assumes ``nexus dashboard`` already started a ``kubectl port-forward`` to
Prometheus (see ``nexus_cli.core.dashboard.start_prometheus_port_forward``) —
this module just queries whatever's listening on that port, the same way the
Grafana iframe assumes its own port-forward is already up.

The PromQL here is deliberately identical to what
``templates/grafana-dashboard.yaml.j2``'s CPU/Memory dashboard already runs,
so the sparklines and the full Grafana panel can never show different
numbers for the same app.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from nexus_cli.core.dashboard import PROMETHEUS_LOCAL_PORT
from nexus_cli.core.output import NexusError

PROMETHEUS_URL = f"http://127.0.0.1:{PROMETHEUS_LOCAL_PORT}"
QUERY_TIMEOUT = 5

DEFAULT_WINDOW = "15m"
TARGET_POINTS = 60  # aim for roughly this many samples regardless of window size

_WINDOW_RE = re.compile(r"^(\d+)(s|m|h)$")
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600}


def cpu_query(app_name: str) -> str:
    # No `container=` filter — see templates/grafana-dashboard.yaml.j2's
    # resource-usage.json comment: on at least one real cluster, cAdvisor's
    # per-container cgroup metrics carry no `container` label at all, only
    # the pod-level aggregate. `namespace` alone is correct and sufficient
    # given one app per namespace.
    return f'sum(rate(container_cpu_usage_seconds_total{{namespace="{app_name}"}}[5m]))'


def memory_query(app_name: str) -> str:
    return f'sum(container_memory_working_set_bytes{{namespace="{app_name}"}})'


def restarts_query(app_name: str) -> str:
    # Same metric + label scoping as templates/grafana-dashboard.yaml.j2's
    # pod-restarts.json, aggregated across pods into one series — the App
    # Detail panel shows "is anything restarting", not a per-pod breakdown.
    return (
        f'sum(increase(kube_pod_container_status_restarts_total'
        f'{{namespace="{app_name}",container="{app_name}"}}[5m]))'
    )


def desired_replicas_query(app_name: str) -> str:
    return f'kube_deployment_spec_replicas{{namespace="{app_name}",deployment="{app_name}"}}'


def available_replicas_query(app_name: str) -> str:
    return (
        f'kube_deployment_status_replicas_available'
        f'{{namespace="{app_name}",deployment="{app_name}"}}'
    )


# These three assume prometheus-flask-exporter's metric names, same as
# templates/grafana-dashboard.yaml.j2's HTTP panels — see that template's
# comment. Harmless to query for an app that doesn't emit them: Prometheus
# just returns no series, which query_range already treats as "no data yet".
def http_request_rate_query(app_name: str) -> str:
    return f'sum(rate(flask_http_request_total{{namespace="{app_name}"}}[5m]))'


def http_error_rate_query(app_name: str) -> str:
    return (
        f'sum(rate(flask_http_request_total'
        f'{{namespace="{app_name}",status=~"5.."}}[5m]))'
    )


def http_latency_p95_query(app_name: str) -> str:
    return (
        "histogram_quantile(0.95, sum(rate("
        f'flask_http_request_duration_seconds_bucket{{namespace="{app_name}"}}[5m]'
        ")) by (le))"
    )


def parse_window(window: str) -> int:
    """Seconds for a window string like ``15m``/``1h``/``90s``.

    Raises NexusError on anything else — this is user input (a query param),
    not something to silently default away.
    """
    match = _WINDOW_RE.match(window)
    if not match:
        raise NexusError(
            what=f"Unsupported metrics window '{window}'.",
            why="Expected a number followed by s, m, or h — e.g. '15m', '1h'.",
            fix="Pass a window like `?window=15m`.",
        )
    value, unit = match.groups()
    return int(value) * _UNIT_SECONDS[unit]


def query_range(promql: str, window_seconds: int) -> list[tuple[float, float]]:
    """(timestamp, value) pairs from Prometheus over the last ``window_seconds``.

    Empty (not raised) if the app has no matching series yet — a freshly
    deployed app with no traffic is a legitimate "nothing to show", not a
    failure. Raises NexusError only when Prometheus itself isn't reachable or
    returns something we can't parse.
    """
    now = time.time()
    step = max(window_seconds // TARGET_POINTS, 1)
    params = urllib.parse.urlencode(
        {"query": promql, "start": now - window_seconds, "end": now, "step": step}
    )
    url = f"{PROMETHEUS_URL}/api/v1/query_range?{params}"
    try:
        with urllib.request.urlopen(url, timeout=QUERY_TIMEOUT) as resp:  # noqa: S310
            payload = json.loads(resp.read())
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        raise NexusError(
            what="Could not reach Prometheus.",
            why=str(exc),
            fix=(
                "`nexus dashboard` normally port-forwards Prometheus for you — if "
                "monitoring isn't installed, run `kubectl port-forward "
                "svc/kube-prom-stack-kube-prome-prometheus 9090:9090 -n monitoring`."
            ),
        ) from exc

    results = payload.get("data", {}).get("result", [])
    if not results:
        return []
    values = results[0].get("values", [])
    return [(float(ts), float(v)) for ts, v in values]


def query_range_many(
    queries: dict[str, str], window_seconds: int
) -> dict[str, list[tuple[float, float]]]:
    """``query_range`` for several named PromQL queries at once, concurrently.

    The metrics endpoint fires ~8 independent queries per poll; run one at a
    time they'd serialize on QUERY_TIMEOUT (5s) each, turning a 15s poll into
    a multi-second stall on a slow/unreachable Prometheus. Threads are fine
    here — urllib.request.urlopen releases the GIL while blocked on I/O.
    Referencing the module-level `query_range` by name (not a captured
    reference) keeps this monkeypatch-friendly for tests, same as every other
    caller in this module.
    """
    with ThreadPoolExecutor(max_workers=max(len(queries), 1)) as pool:
        futures = {name: pool.submit(query_range, q, window_seconds) for name, q in queries.items()}
        return {name: future.result() for name, future in futures.items()}
