"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { ApiError, PodSummary, listPods, triggerChaos } from "@/lib/api";

const NORMAL_POLL_MS = 3000;
const RECOVERY_POLL_MS = 1000;
const RECOVERY_WINDOW_MS = 20000;

// Grafana isn't exposed outside the cluster by `nexus deploy` — doing so
// would need an Ingress/NodePort decision this project hasn't made. The
// panel below expects a `kubectl port-forward svc/kube-prom-stack-grafana
// 3000:80 -n monitoring` (or NEXT_PUBLIC_GRAFANA_URL pointed at wherever
// Grafana is reachable); this is a documented manual step, not automated.
const GRAFANA_BASE = process.env.NEXT_PUBLIC_GRAFANA_URL ?? "http://localhost:3000";
const GRAFANA_CHECK_INTERVAL_MS = 10000;
const GRAFANA_CHECK_TIMEOUT_MS = 2000;

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

export default function AppDetailPage() {
  const params = useParams<{ name: string }>();
  const name = decodeURIComponent(params.name);

  const [pods, setPods] = useState<PodSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [triggering, setTriggering] = useState(false);
  const [chaosMessage, setChaosMessage] = useState<string | null>(null);
  const recoveryUntil = useRef<number>(0);
  const [recoveryActive, setRecoveryActive] = useState(false);
  const [grafanaReachable, setGrafanaReachable] = useState<boolean | null>(null);

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
                <span className="muted">restarts={pod.restarts}</span>
                {pod.problem && <span className="badge badge-danger">{pod.problem}</span>}
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="section">
        <h2>Metrics</h2>
        {grafanaReachable === false && (
          <p className="error-box" style={{ marginBottom: "0.5rem" }}>
            Grafana isn&apos;t reachable at {GRAFANA_BASE} — this is expected until you run{" "}
            <code>kubectl port-forward svc/kube-prom-stack-grafana 3000:80 -n monitoring</code>.
            The panel below will appear automatically once it is.
          </p>
        )}
        {grafanaReachable !== false && (
          <iframe
            className="grafana-frame"
            src={`${GRAFANA_BASE}/d/${encodeURIComponent(name)}-availability/${encodeURIComponent(name)}-pod-availability?orgId=1&refresh=10s&kiosk`}
            title={`${name} Grafana dashboard`}
          />
        )}
        <p style={{ marginTop: "0.5rem" }}>
          <a
            href={`${GRAFANA_BASE}/d/${encodeURIComponent(name)}-availability`}
            target="_blank"
            rel="noopener noreferrer"
            className="muted"
          >
            Open full Grafana dashboard →
          </a>
        </p>
      </div>
    </div>
  );
}
