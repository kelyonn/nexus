"use client";

import { MetricPoint } from "@/lib/api";

export interface SparklineSeries {
  label: string;
  points: MetricPoint[];
  color?: string;
}

interface SparklineProps {
  title: string;
  series: SparklineSeries[];
  formatValue: (v: number) => string;
  width?: number;
  height?: number;
}

const DEFAULT_COLORS = ["var(--accent)", "var(--accent-2)"];

/** A minimal inline-SVG sparkline panel — no charting library, matching the
 * rest of this frontend's zero-runtime-dependency approach. Supports one or
 * more overlaid series (e.g. desired vs. available replicas) sharing a
 * single y-scale so they stay visually comparable. */
export default function Sparkline({ title, series, formatValue, width = 240, height = 48 }: SparklineProps) {
  const hasData = series.some((s) => s.points.length > 0);

  if (!hasData) {
    return (
      <div>
        <p className="muted" style={{ marginBottom: "0.2rem" }}>
          {title}
        </p>
        <p className="muted">No data yet</p>
      </div>
    );
  }

  const allValues = series.flatMap((s) => s.points.map((p) => p.value));
  const min = Math.min(...allValues);
  const max = Math.max(...allValues);
  const range = max - min || 1; // avoid a divide-by-zero on a perfectly flat line

  return (
    <div>
      <p className="muted" style={{ marginBottom: "0.3rem" }}>
        {title}
      </p>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width="100%"
        height={height}
        preserveAspectRatio="none"
        role="img"
        aria-label={title}
      >
        {series.map((s, i) => {
          if (s.points.length === 0) return null;
          const coords = s.points
            .map((p, j) => {
              const x = (j / Math.max(s.points.length - 1, 1)) * width;
              const y = height - ((p.value - min) / range) * height;
              return `${x.toFixed(1)},${y.toFixed(1)}`;
            })
            .join(" ");
          return (
            <polyline
              key={s.label}
              points={coords}
              fill="none"
              stroke={s.color ?? DEFAULT_COLORS[i % DEFAULT_COLORS.length]}
              strokeWidth="2"
            />
          );
        })}
      </svg>
      <div className="sparkline-legend">
        {series.map((s, i) => {
          const latest = s.points.at(-1)?.value;
          return (
            <span key={s.label} className="sparkline-legend-item muted">
              <i
                className="legend-dot"
                style={{ background: s.color ?? DEFAULT_COLORS[i % DEFAULT_COLORS.length] }}
              />
              {series.length > 1 ? `${s.label}: ` : ""}
              {latest === undefined ? "—" : formatValue(latest)}
            </span>
          );
        })}
      </div>
    </div>
  );
}
