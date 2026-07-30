/**
 * Typed client for the dashboard backend (PRD §10 — Local Backend). Every
 * request goes through the same-origin `/api/*` path, which next.config.ts
 * rewrites to the FastAPI backend — the browser never talks to
 * 127.0.0.1:3002 directly.
 *
 * The response/request shapes below come from ./api.generated (generated
 * from dashboard/backend/routes.py's Pydantic models — see
 * scripts/generate_dashboard_types.py) rather than being hand-written here,
 * so this file can't silently drift from what the backend actually
 * returns. A few are re-exported under shorter, frontend-only names.
 */

import type {
  AppSummary,
  ChaosRequest,
  ChaosResponse,
  MetricPoint,
  MetricsResponse,
  PodSummary,
  SyncEventOut,
  SyncLogResponse,
} from "./api.generated";
import { getToken } from "./token";

export type { AppSummary, ChaosRequest, ChaosResponse, MetricPoint, PodSummary };
export type SyncEvent = SyncEventOut;
export type SyncLog = SyncLogResponse;
export type Metrics = MetricsResponse;

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
): Promise<ChaosResponse> {
  const token = getToken();
  const body: ChaosRequest = {
    action: options.action ?? "pod-kill",
    kill_all: options.killAll ?? false,
  };
  const resp = await fetch(`/api/apps/${encodeURIComponent(name)}/chaos`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    const detail = await resp.json().catch(() => null);
    throw new ApiError(detail?.detail ?? "Chaos trigger failed.", resp.status);
  }
  return resp.json();
}
