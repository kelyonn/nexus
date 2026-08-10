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

function formatCount(n: number): string {
  return Math.round(n).toString();
}

function formatReqps(n: number): string {
  return `${n.toFixed(2)}/s`;
}

function formatLatency(seconds: number): string {
  return `${Math.round(seconds * 1000)}ms`;
}

// `nexus dashboard` best-effort port-forwards Grafana for anyone who wants
// to drill past what's on this page (raw PromQL, alerting, dashboard
// editing) — this is a plain link to it, not an embed (an iframe here would
// just render Grafana's own login form until the browser already holds a
// session cookie for it, which is a worse experience than a link that
// requires the one click). Point NEXT_PUBLIC_GRAFANA_URL elsewhere to
// override the target.
const GRAFANA_BASE = process.env.NEXT_PUBLIC_GRAFANA_URL ?? "http://localhost:3000";

// templates/grafana-dashboard.yaml.j2 generates exactly one dashboard per
// app, uid `<app-name>-overview` — every panel (replicas, restarts, CPU/
// memory, and the HTTP ones if app.metricsPath is set) lives there, so this
// links straight to it instead of Grafana's generic home screen.
function grafanaDashboardUrl(name: string): string {
  const uid = `${name}-overview`;
  return `${GRAFANA_BASE}/d/${encodeURIComponent(uid)}/${encodeURIComponent(uid)}`;
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
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
        <h1>{name}</h1>
        <a href={grafanaDashboardUrl(name)} target="_blank" rel="noopener noreferrer" className="muted">
          Open Grafana ↗
        </a>
      </div>

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
        <h2>Metrics</h2>
        {metricsError && <p className="error-box">{metricsError}</p>}
        {!metricsError && metrics === null && <p className="muted">Loading…</p>}
        {!metricsError && metrics !== null && (
          <div className="metrics-grid">
            <div className="metric-panel">
              <Sparkline title="CPU" series={[{ label: "cpu", points: metrics.cpu }]} formatValue={formatCpu} />
            </div>
            <div className="metric-panel">
              <Sparkline
                title="Memory"
                series={[{ label: "memory", points: metrics.memory }]}
                formatValue={formatMemory}
              />
            </div>
            <div className="metric-panel">
              <Sparkline
                title="Replicas"
                series={[
                  { label: "desired", points: metrics.desired_replicas },
                  { label: "available", points: metrics.available_replicas },
                ]}
                formatValue={formatCount}
              />
            </div>
            <div className="metric-panel">
              <Sparkline
                title="Restarts (5m)"
                series={[{ label: "restarts", points: metrics.restarts }]}
                formatValue={formatCount}
              />
            </div>
            {hasHttpMetrics && (
              <>
                <div className="metric-panel">
                  <Sparkline
                    title="Request Rate"
                    series={[{ label: "requests", points: metrics.http_request_rate }]}
                    formatValue={formatReqps}
                  />
                </div>
                <div className="metric-panel">
                  <Sparkline
                    title="Error Rate (5xx)"
                    series={[{ label: "errors", points: metrics.http_error_rate }]}
                    formatValue={formatReqps}
                  />
                </div>
                <div className="metric-panel">
                  <Sparkline
                    title="P95 Latency"
                    series={[{ label: "p95", points: metrics.http_latency_p95 }]}
                    formatValue={formatLatency}
                  />
                </div>
              </>
            )}
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
