"use client";

import { useEffect, useState } from "react";
import { ApiError, SyncLog, getSyncLog, listApps } from "@/lib/api";
import { healthBadgeClass, syncBadgeClass } from "@/lib/badges";

const POLL_INTERVAL_MS = 5000;

interface Row {
  app: string;
  deployedAt: string | null;
  revision: string | null;
  syncStatus: string;
  healthStatus: string;
}

// The backend's /synclog is per-app (PRD §10's API table has no aggregate
// endpoint), and a local dev tool expects a handful of apps at most — so
// this page fetches each managed app's log and merges them client-side
// rather than adding a new backend endpoint for what's a small, cheap fan-out.
async function fetchAllRows(): Promise<Row[]> {
  const apps = await listApps();
  const logs = await Promise.all(apps.map((a) => getSyncLog(a.name)));
  const rows: Row[] = [];
  for (const log of logs as SyncLog[]) {
    for (const event of log.history) {
      rows.push({
        app: log.app,
        deployedAt: event.deployed_at,
        revision: event.revision,
        syncStatus: log.sync_status,
        healthStatus: log.health_status,
      });
    }
  }
  rows.sort((a, b) => (b.deployedAt ?? "").localeCompare(a.deployedAt ?? ""));
  return rows;
}

export default function SyncLogPage() {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function refresh() {
      try {
        const data = await fetchAllRows();
        if (!cancelled) {
          setRows(data);
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
      <h1>GitOps Log</h1>
      {error && <p className="error-box">{error}</p>}
      {!error && rows === null && <p className="muted">Loading…</p>}
      {!error && rows !== null && rows.length === 0 && (
        <p className="muted">No sync history yet — deploy an app to see it here.</p>
      )}
      {rows && rows.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Deployed</th>
              <th>App</th>
              <th>Status</th>
              <th>Revision</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={`${row.app}-${row.revision}-${i}`}>
                <td>{row.deployedAt ?? "—"}</td>
                <td>{row.app}</td>
                <td>
                  <div className="badge-row">
                    <span className={syncBadgeClass(row.syncStatus)}>{row.syncStatus}</span>
                    <span className={healthBadgeClass(row.healthStatus)}>{row.healthStatus}</span>
                  </div>
                </td>
                <td>
                  <code>{row.revision ? row.revision.slice(0, 7) : "—"}</code>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
