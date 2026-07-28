/** Maps ArgoCD's sync/health status strings to the badge color PRD §10.1 specifies. */

export function syncBadgeClass(status: string): string {
  switch (status) {
    case "Synced":
      return "badge badge-ok";
    case "OutOfSync":
      return "badge badge-warn";
    default:
      return "badge badge-neutral";
  }
}

export function healthBadgeClass(status: string): string {
  switch (status) {
    case "Healthy":
      return "badge badge-ok";
    case "Progressing":
      return "badge badge-warn";
    case "Degraded":
      return "badge badge-danger";
    default:
      return "badge badge-neutral";
  }
}
