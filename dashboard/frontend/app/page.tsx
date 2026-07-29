"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ApiError, AppSummary, listApps } from "@/lib/api";
import { healthBadgeClass, syncBadgeClass } from "@/lib/badges";

const POLL_INTERVAL_MS = 3000;

export default function OverviewPage() {
  const [apps, setApps] = useState<AppSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function refresh() {
      try {
        const data = await listApps();
        if (!cancelled) {
          setApps(data);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : "Could not reach the dashboard backend.");
        }
      }
    }

    refresh();
    const id = setInterval(refresh, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  return (
    <div>
      <h1>Overview</h1>
      {error && <p className="error-box">{error}</p>}
      {!error && apps === null && <p className="muted">Loading…</p>}
      {!error && apps !== null && apps.length === 0 && (
        <p className="muted">
          No Nexus-managed apps found. Run <code>nexus deploy</code> against a cluster this
          dashboard can reach.
        </p>
      )}
      {apps && apps.length > 0 && (
        <div className="grid">
          {apps.map((app) => (
            <Link key={app.name} href={`/apps/${encodeURIComponent(app.name)}`} className="card">
              <span className="card-title">{app.name}</span>
              <span className="muted">
                {app.available_replicas} / {app.desired_replicas} replicas
              </span>
              <div className="badge-row">
                <span className={syncBadgeClass(app.sync_status)}>{app.sync_status}</span>
                <span className={healthBadgeClass(app.health_status)}>{app.health_status}</span>
              </div>
              {app.last_sync_time && (
                <span className="muted">Last sync: {app.last_sync_time}</span>
              )}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
