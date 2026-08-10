/**
 * GENERATED FILE — do not edit by hand.
 *
 * Regenerate with `python3 scripts/generate_dashboard_types.py` after
 * changing a Pydantic model in dashboard/backend/routes.py. CI fails if
 * this file is stale relative to those models (see
 * .github/workflows/ci.yml's dashboard-frontend job).
 */

export interface AppSummary {
  name: string;
  sync_status: string;
  health_status: string;
  last_sync_time: string | null;
  desired_replicas: number;
  available_replicas: number;
  has_http_metrics: boolean;
}
export interface ChaosRequest {
  action?: string;
  kill_all?: boolean;
}
export interface ChaosResponse {
  run_name: string;
}
export interface MetricPoint {
  timestamp: number;
  value: number;
}
export interface MetricsResponse {
  cpu: MetricPoint[];
  memory: MetricPoint[];
  restarts: MetricPoint[];
  desired_replicas: MetricPoint[];
  available_replicas: MetricPoint[];
  http_request_rate: MetricPoint[];
  http_error_rate: MetricPoint[];
  http_latency_p95: MetricPoint[];
}
export interface PodSummary {
  name: string;
  phase: string;
  restarts: number;
  problem: string | null;
  created_at: string | null;
}
export interface SyncEventOut {
  revision: string | null;
  deployed_at: string | null;
  subject: string | null;
}
export interface SyncLogResponse {
  app: string;
  sync_status: string;
  health_status: string;
  last_sync_time: string | null;
  history: SyncEventOut[];
}
