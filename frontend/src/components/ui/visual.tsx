import { useEffect, useRef, useState } from "react";
import { cx } from "./primitives";

/* ---------------------------------------------------------------------------------------------
 * StockAvatar: a stable coloured badge with a stock's initials, so lists read at a glance.
 * The hue comes from the symbol, so a stock always looks the same everywhere in the app.
 * ------------------------------------------------------------------------------------------- */

function hue(text: string): number {
  let h = 0;
  for (let i = 0; i < text.length; i++) h = (h * 31 + text.charCodeAt(i)) >>> 0;
  return h % 360;
}

function initials(symbol: string): string {
  const clean = symbol.replace(/[^A-Za-z0-9&]/g, "");
  return (clean.slice(0, 2) || "?").toUpperCase();
}

export function StockAvatar({ symbol, size = 28, className }: { symbol: string; size?: number; className?: string }) {
  const h = hue(symbol);
  return (
    <span
      aria-hidden
      className={cx("fc-avatar inline-flex shrink-0 items-center justify-center rounded-lg font-semibold", className)}
      style={
        {
          width: size,
          height: size,
          fontSize: Math.max(9, Math.round(size * 0.36)),
          "--av-h": h,
        } as React.CSSProperties
      }
    >
      {initials(symbol)}
    </span>
  );
}

/* ---------------------------------------------------------------------------------------------
 * Sparkline: a tiny trend line from real closes. Colour follows the direction over the window.
 * ------------------------------------------------------------------------------------------- */

export function Sparkline({
  points,
  width = 72,
  height = 22,
  className,
  fill = true,
}: {
  points: number[] | undefined;
  width?: number;
  height?: number;
  className?: string;
  fill?: boolean;
}) {
  const id = useRef(`sp${Math.random().toString(36).slice(2, 8)}`).current;
  if (!points || points.length < 2) return <span className={cx("inline-block", className)} style={{ width, height }} />;
  const min = Math.min(...points);
  const max = Math.max(...points);
  const span = max - min || 1;
  const step = width / (points.length - 1);
  const xy = points.map((p, i) => [i * step, height - 2 - ((p - min) / span) * (height - 4)] as const);
  const line = xy.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const up = points[points.length - 1]! >= points[0]!;
  const color = up ? "var(--up)" : "var(--down)";
  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className={cx("overflow-visible", className)}
      aria-hidden
    >
      {fill && (
        <>
          <defs>
            <linearGradient id={id} x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity="0.22" />
              <stop offset="100%" stopColor={color} stopOpacity="0" />
            </linearGradient>
          </defs>
          <path d={`${line} L${width},${height} L0,${height} Z`} fill={`url(#${id})`} />
        </>
      )}
      <path d={line} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={xy[xy.length - 1]![0]} cy={xy[xy.length - 1]![1]} r="2" fill={color} />
    </svg>
  );
}

/* ---------------------------------------------------------------------------------------------
 * AnimatedNumber: eases from the previous value to the new one, so changes are felt.
 * ------------------------------------------------------------------------------------------- */

const reduceMotion = () =>
  typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

export function AnimatedNumber({
  value,
  format,
  duration = 700,
}: {
  value: number | null | undefined;
  format: (v: number) => string;
  duration?: number;
}) {
  const [shown, setShown] = useState(value ?? 0);
  const from = useRef(value ?? 0);
  useEffect(() => {
    if (value == null) return;
    if (reduceMotion()) {
      setShown(value);
      from.current = value;
      return;
    }
    const start = performance.now();
    const a = from.current;
    let raf = 0;
    const tick = (t: number) => {
      const k = Math.min(1, (t - start) / duration);
      const eased = 1 - Math.pow(1 - k, 3);
      setShown(a + (value - a) * eased);
      if (k < 1) raf = requestAnimationFrame(tick);
      else from.current = value;
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [value, duration]);
  if (value == null) return <>—</>;
  return <>{format(shown)}</>;
}

/* ---------------------------------------------------------------------------------------------
 * Ring: a progress ring for shares and rates (win rate, track record, time in market).
 * ------------------------------------------------------------------------------------------- */

export function Ring({
  value,
  size = 44,
  stroke = 4,
  tone = "accent",
  children,
}: {
  value: number | null | undefined;
  size?: number;
  stroke?: number;
  tone?: "accent" | "up" | "down" | "caution";
  children?: React.ReactNode;
}) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const v = value == null ? 0 : Math.max(0, Math.min(1, value));
  const color = { accent: "var(--accent)", up: "var(--up)", down: "var(--down)", caution: "var(--caution)" }[tone];
  return (
    <span className="relative inline-flex shrink-0 items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90" aria-hidden>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--surface-3)" strokeWidth={stroke} />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={color}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={c * (1 - v)}
          className="fc-ring-arc"
        />
      </svg>
      {children && <span className="absolute inset-0 flex items-center justify-center">{children}</span>}
    </span>
  );
}

/* ---------------------------------------------------------------------------------------------
 * BreadthBar: how many went up against how many went down, as one split bar.
 * ------------------------------------------------------------------------------------------- */

export function BreadthBar({ up, down, flat = 0 }: { up: number; down: number; flat?: number }) {
  const total = up + down + flat || 1;
  return (
    <div className="flex h-2 w-full overflow-hidden rounded-full bg-surface-3" aria-hidden>
      <div className="fc-grow h-full bg-up" style={{ width: `${(up / total) * 100}%` }} />
      <div className="h-full bg-faint/50" style={{ width: `${(flat / total) * 100}%` }} />
      <div className="fc-grow h-full bg-down" style={{ width: `${(down / total) * 100}%` }} />
    </div>
  );
}
