"use client";

import { MetricPoint } from "@/lib/api";

interface SparklineProps {
  label: string;
  points: MetricPoint[];
  formatValue: (v: number) => string;
  width?: number;
  height?: number;
}

/** A minimal inline-SVG sparkline — no charting library, matching the rest
 * of this frontend's zero-runtime-dependency approach. */
export default function Sparkline({
  label,
  points,
  formatValue,
  width = 240,
  height = 48,
}: SparklineProps) {
  if (points.length === 0) {
    return (
      <div>
        <p className="muted" style={{ marginBottom: "0.2rem" }}>
          {label}
        </p>
        <p className="muted">No data yet</p>
      </div>
    );
  }

  const values = points.map((p) => p.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1; // avoid a divide-by-zero on a perfectly flat line

  const coords = points
    .map((p, i) => {
      const x = (i / Math.max(points.length - 1, 1)) * width;
      const y = height - ((p.value - min) / range) * height;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  const latest = values[values.length - 1];

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between" }}>
        <span className="muted">{label}</span>
        <span className="muted">{formatValue(latest)}</span>
      </div>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width="100%"
        height={height}
        preserveAspectRatio="none"
        role="img"
        aria-label={`${label} sparkline, current value ${formatValue(latest)}`}
      >
        <polyline points={coords} fill="none" stroke="var(--accent)" strokeWidth="2" />
      </svg>
    </div>
  );
}
