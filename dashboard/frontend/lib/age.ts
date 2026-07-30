/** Relative age formatting for pod creationTimestamp, matching `kubectl get pods`'s AGE column convention (largest unit only). */

export function formatAge(createdAt: string | null): string {
  if (!createdAt) return "—";
  const createdMs = Date.parse(createdAt);
  if (Number.isNaN(createdMs)) return "—";

  const seconds = Math.max(0, Math.floor((Date.now() - createdMs) / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;
  const days = Math.floor(hours / 24);
  return `${days}d`;
}
