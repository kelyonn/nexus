/**
 * The per-session dashboard token (PRD §13). `nexus dashboard` generates it
 * fresh at launch and opens the browser at `/?token=...`; this module pulls
 * it out of the URL exactly once, stores it in sessionStorage (cleared when
 * the tab closes, never written to disk), and strips it from the address
 * bar so it doesn't linger somewhere a screenshot or browser history would
 * capture it.
 *
 * Only the mutating chaos-trigger call needs it — everything else is a plain
 * unauthenticated GET (see dashboard/backend/auth.py).
 */

const STORAGE_KEY = "nexus_dashboard_token";

export function captureTokenFromUrl(): void {
  if (typeof window === "undefined") return;

  const url = new URL(window.location.href);
  const token = url.searchParams.get("token");
  if (token) {
    window.sessionStorage.setItem(STORAGE_KEY, token);
    url.searchParams.delete("token");
    window.history.replaceState({}, "", url.toString());
  }
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.sessionStorage.getItem(STORAGE_KEY);
}
