"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import {
  ApiError,
  Metrics,
  PodSummary,
  getMetrics,
  listApps,
  listPods,
  triggerChaos,
} from "@/lib/api";
import { formatAge } from "@/lib/age";
import Sparkline from "@/app/Sparkline";

const NORMAL_POLL_MS = 3000;
const RECOVERY_POLL_MS = 1000;
const RECOVERY_WINDOW_MS = 20000;
const METRICS_POLL_MS = 15000; // 5m-rate CPU data doesn't change meaningfully faster than this

function formatCpu(cores: number): string {
  return `${Math.round(cores * 1000)}m`;
}

function formatMemory(bytes: number): string {
  return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
}

// Grafana isn't exposed outside the cluster by `nexus deploy` — doing so
// would need an Ingress/NodePort decision this project hasn't made. Instead
// `nexus dashboard` starts a `kubectl port-forward` to it automatically (see
// core/dashboard.start_grafana_port_forward), so these panels normally just
// work. The message below is the fallback for when they don't: no Grafana on
// the cluster, the forward died, or the dashboard was started some other way.
// Point NEXT_PUBLIC_GRAFANA_URL elsewhere to override the target.
const GRAFANA_BASE = process.env.NEXT_PUBLIC_GRAFANA_URL ?? "http://localhost:3000";
const GRAFANA_CHECK_INTERVAL_MS = 10000;
const GRAFANA_CHECK_TIMEOUT_MS = 2000;

// `nexus deploy` generates all four of these dashboards per app (see
// templates/grafana-dashboard.yaml.j2) — this just needs to embed all of
// them, not invent new metrics. Each is real cluster data (kube-state-metrics
// + cAdvisor via kube-prometheus-stack), not app-level instrumentation, so
// no changes to the deployed app are needed for any of these to work.
const CLUSTER_PANELS = [
  { slug: "availability", label: "Pod Availability" },
  { slug: "restarts", label: "Pod Restarts" },
  { slug: "resources", label: "CPU / Memory Usage" },
  { slug: "replicas", label: "Desired vs Running" },
] as const;

// Only rendered by `nexus deploy` when app.metricsPath is set (PRD §10.4) —
// unlike CLUSTER_PANELS above, these dashboards don't exist in Grafana for
// apps that never opted in, so they're appended conditionally once we know
// (via has_http_metrics from /api/apps) that this app actually has them.
const HTTP_METRIC_PANELS = [
  { slug: "requests", label: "HTTP Request Rate" },
  { slug: "errors", label: "HTTP Error Rate" },
  { slug: "latency", label: "HTTP P95 Latency" },
] as const;

// A cross-origin iframe that fails to load (connection refused, nothing
// port-forwarded) just renders as a blank/broken frame with no error event
// we can hook into — indistinguishable from "actually broken" to a user who
// hasn't read the paragraph above it. A lightweight reachability probe lets
// us show an honest "not reachable, here's the fix" message instead of
// silently failing. `no-cors` avoids a CORS read (which would fail even
// when Grafana IS running) — we only care whether the connection succeeds.
async function isGrafanaReachable(): Promise<boolean> {
  try {
    await fetch(`${GRAFANA_BASE}/api/health`, {
      mode: "no-cors",
      signal: AbortSignal.timeout(GRAFANA_CHECK_TIMEOUT_MS),
    });
    return true;
  } catch {
    return false;
  }
}

// This used to be app/apps/[name]/page.tsx, a dynamic route. A static export
// (PRD §13 — pip-installable dashboard, no Node runtime required) can't serve
// arbitrary dynamic segments without knowing every app name at build time, so
// this reads ?name= instead — same data, same behavior, just a query string.
// useSearchParams() requires a Suspense boundary for static export builds
// (see the default export below), which is why the real work lives in this
// separate inner component.
function AppDetailContent() {
  const searchParams = useSearchParams();
  const name = searchParams.get("name") ?? "";

  const [pods, setPods] = useState<PodSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [triggering, setTriggering] = useState(false);
  const [chaosMessage, setChaosMessage] = useState<string | null>(null);
  const recoveryUntil = useRef<number>(0);
  const [recoveryActive, setRecoveryActive] = useState(false);
  const [grafanaReachable, setGrafanaReachable] = useState<boolean | null>(null);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [metricsError, setMetricsError] = useState<string | null>(null);
  const [hasHttpMetrics, setHasHttpMetrics] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function checkHttpMetrics() {
      if (!name) return;
      try {
        const apps = await listApps();
        const match = apps.find((a) => a.name === name);
        if (!cancelled && match) setHasHttpMetrics(match.has_http_metrics);
      } catch {
        // Best-effort — if this fails, the HTTP panels just don't show up,
        // same as if the app never had metricsPath set.
      }
    }

    checkHttpMetrics();
    return () => {
      cancelled = true;
    };
  }, [name]);

  useEffect(() => {
    let cancelled = false;

    async function refreshMetrics() {
      if (!name) return;
      try {
        const data = await getMetrics(name);
        if (!cancelled) {
          setMetrics(data);
          setMetricsError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setMetricsError(err instanceof ApiError ? err.message : "Could not fetch metrics.");
        }
      }
    }

    refreshMetrics();
    const id = setInterval(refreshMetrics, METRICS_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [name]);

  useEffect(() => {
    let cancelled = false;

    async function checkGrafana() {
      const reachable = await isGrafanaReachable();
      if (!cancelled) setGrafanaReachable(reachable);
    }

    checkGrafana();
    const id = setInterval(checkGrafana, GRAFANA_CHECK_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;

    async function tick() {
      if (!name) return;
      try {
        const data = await listPods(name);
        if (!cancelled) {
          setPods(data);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : "Could not reach the dashboard backend.");
        }
      }
      if (cancelled) return;
      const active = Date.now() < recoveryUntil.current;
      setRecoveryActive(active);
      timer = setTimeout(tick, active ? RECOVERY_POLL_MS : NORMAL_POLL_MS);
    }

    tick();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [name]);

  async function handleTriggerChaos() {
    if (!name) return;
    setTriggering(true);
    setChaosMessage(null);
    try {
      const result = await triggerChaos(name);
      setChaosMessage(`Started ${result.run_name} — watching for recovery.`);
      recoveryUntil.current = Date.now() + RECOVERY_WINDOW_MS;
      setRecoveryActive(true);
    } catch (err) {
      setChaosMessage(err instanceof ApiError ? err.message : "Could not trigger chaos.");
    } finally {
      setTriggering(false);
    }
  }

  const panels: readonly { slug: string; label: string }[] = hasHttpMetrics
    ? [...CLUSTER_PANELS, ...HTTP_METRIC_PANELS]
    : CLUSTER_PANELS;

  if (!name) {
    return (
      <div>
        <Link href="/" className="back-link">
          ← Overview
        </Link>
        <p className="error-box" style={{ marginTop: "1rem" }}>
          No app specified — open this page via a card on the{" "}
          <Link href="/">Overview</Link> grid.
        </p>
      </div>
    );
  }

  return (
    <div>
      <Link href="/" className="back-link">
        ← Overview
      </Link>
      <h1>{name}</h1>

      <button className="btn btn-danger" disabled={triggering} onClick={handleTriggerChaos}>
        {triggering ? "Triggering…" : "Trigger Chaos (kill one pod)"}
      </button>
      {chaosMessage && <p className="muted" style={{ marginTop: "0.5rem" }}>{chaosMessage}</p>}

      <div className="section">
        <h2>Pods</h2>
        {recoveryActive && (
          <p className="recovery-banner">Chaos experiment in progress — watching pods recover…</p>
        )}
        {error && <p className="error-box">{error}</p>}
        {!error && pods === null && <p className="muted">Loading…</p>}
        {!error && pods !== null && pods.length === 0 && <p className="muted">No pods found.</p>}
        {pods && pods.length > 0 && (
          <div>
            {pods.map((pod) => (
              <div key={pod.name} className="pod-row">
                <span>{pod.name}</span>
                <span className="muted">{pod.phase}</span>
                <span className="muted">age={formatAge(pod.created_at)}</span>
                <span className="muted">restarts={pod.restarts}</span>
                {pod.problem && <span className="badge badge-danger">{pod.problem}</span>}
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="section">
        <h2>Resource Usage</h2>
        {metricsError && <p className="error-box">{metricsError}</p>}
        {!metricsError && metrics === null && <p className="muted">Loading…</p>}
        {!metricsError && metrics !== null && (
          <div className="metrics-grid">
            <Sparkline label="CPU" points={metrics.cpu} formatValue={formatCpu} />
            <Sparkline label="Memory" points={metrics.memory} formatValue={formatMemory} />
          </div>
        )}
      </div>

      <div className="section">
        <h2>Metrics</h2>
        {grafanaReachable === false && (
          <p className="error-box" style={{ marginBottom: "0.5rem" }}>
            Grafana isn&apos;t reachable at {GRAFANA_BASE}. <code>nexus dashboard</code> normally
            port-forwards it for you — if monitoring isn&apos;t installed on this cluster, or you
            started the dashboard another way, run{" "}
            <code>kubectl port-forward svc/kube-prom-stack-grafana 3000:80 -n monitoring</code>.
            The panels appear automatically once it&apos;s up.
          </p>
        )}
        {grafanaReachable !== false && (
          <div className="metrics-grid">
            {panels.map((panel) => (
              <div key={panel.slug}>
                <p className="muted" style={{ marginBottom: "0.3rem" }}>
                  {panel.label}
                </p>
                <iframe
                  className="grafana-frame"
                  src={`${GRAFANA_BASE}/d/${encodeURIComponent(name)}-${panel.slug}/${encodeURIComponent(name)}-${panel.slug}?orgId=1&refresh=10s&kiosk`}
                  title={`${name} ${panel.label}`}
                />
                <p style={{ marginTop: "0.3rem" }}>
                  <a
                    href={`${GRAFANA_BASE}/d/${encodeURIComponent(name)}-${panel.slug}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="muted"
                  >
                    Open full dashboard →
                  </a>
                </p>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default function AppDetailPage() {
  return (
    <Suspense fallback={<p className="muted">Loading…</p>}>
      <AppDetailContent />
    </Suspense>
  );
}
