/**
 * Typed client for the dashboard backend (PRD §10 — Local Backend). Every
 * request goes through the same-origin `/api/*` path, which next.config.ts
 * rewrites to the FastAPI backend — the browser never talks to
 * 127.0.0.1:3002 directly.
 */

import { getToken } from "./token";

export interface AppSummary {
  name: string;
  sync_status: string;
  health_status: string;
  last_sync_time: string | null;
  desired_replicas: number;
  available_replicas: number;
  has_http_metrics: boolean;
}

export interface PodSummary {
  name: string;
  phase: string;
  restarts: number;
  problem: string | null;
  created_at: string | null;
}

export interface SyncEvent {
  revision: string | null;
  deployed_at: string | null;
  subject: string | null;
}

export interface SyncLog {
  app: string;
  sync_status: string;
  health_status: string;
  last_sync_time: string | null;
  history: SyncEvent[];
}

export interface MetricPoint {
  timestamp: number;
  value: number;
}

export interface Metrics {
  cpu: MetricPoint[];
  memory: MetricPoint[];
}

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

async function apiGet<T>(path: string): Promise<T> {
  const resp = await fetch(`/api${path}`, { cache: "no-store" });
  if (!resp.ok) {
    const detail = await resp.json().catch(() => null);
    throw new ApiError(detail?.detail ?? `Request to ${path} failed.`, resp.status);
  }
  return resp.json() as Promise<T>;
}

export function listApps(): Promise<AppSummary[]> {
  return apiGet<AppSummary[]>("/apps");
}

export function listPods(name: string): Promise<PodSummary[]> {
  return apiGet<PodSummary[]>(`/apps/${encodeURIComponent(name)}/pods`);
}

export function getSyncLog(name: string): Promise<SyncLog> {
  return apiGet<SyncLog>(`/apps/${encodeURIComponent(name)}/synclog`);
}

export function getMetrics(name: string, window = "15m"): Promise<Metrics> {
  const params = new URLSearchParams({ window });
  return apiGet<Metrics>(`/apps/${encodeURIComponent(name)}/metrics?${params}`);
}

export async function triggerChaos(
  name: string,
  options: { action?: string; killAll?: boolean } = {},
): Promise<{ run_name: string }> {
  const token = getToken();
  const resp = await fetch(`/api/apps/${encodeURIComponent(name)}/chaos`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({
      action: options.action ?? "pod-kill",
      kill_all: options.killAll ?? false,
    }),
  });
  if (!resp.ok) {
    const detail = await resp.json().catch(() => null);
    throw new ApiError(detail?.detail ?? "Chaos trigger failed.", resp.status);
  }
  return resp.json();
}
