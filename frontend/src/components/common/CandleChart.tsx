import { useEffect, useMemo, useState } from 'react';
import { ResponsiveContainer } from 'recharts';
import { fmtInt, fmtPrice } from '../../features/company/priceStats';
import type { MarketPricePoint } from '../../types/api';

const UP = '#2ecc8f';
const DOWN = '#ff5d73';
const GRID = '#1c2942';
const MUTED = '#8fa0b8';
const TIP_BG = '#141f36';
const TIP_BORDER = '#22304d';

const MIN_SPAN = 10;

function niceTicks(min: number, max: number, count: number): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max) || min === max) {
    return [min];
  }
  const span = max - min;
  const raw = span / Math.max(1, count - 1);
  const mag = 10 ** Math.floor(Math.log10(raw));
  const norm = raw / mag;
  const step = (norm < 1.5 ? 1 : norm < 3.5 ? 2 : norm < 7.5 ? 5 : 10) * mag;
  const ticks: number[] = [];
  for (let v = Math.ceil(min / step) * step; v <= max + 1e-9; v += step) {
    ticks.push(Number(v.toFixed(10)));
  }
  return ticks.length > 0 ? ticks : [min, max];
}

/** Interactive OHLC candlestick chart over stored bars (Upstox-style).
 *
 *  Pure SVG — no new dependencies. Green/red candles from real open/close
 *  (bullish when close >= open), price + date axes, hover tooltip with OHLC
 *  values, volume strip, dashed last-price line. Fixed scale: the 1M/3M/6M/
 *  1Y/All presets upstream are the only way to change the displayed range
 *  (no wheel/drag zoom, so page scrolling never rescales the chart).
 */
/** Inner SVG renderer (exported for unit tests — jsdom reports zero width
 *  to ResponsiveContainer, so tests drive this directly with fixed dims). */
export function CandleSvg({
  data,
  width,
  height,
  rangeBars,
}: {
  data: MarketPricePoint[];
  width: number;
  height: number;
  rangeBars: number;
}) {
  const [hover, setHover] = useState<number | null>(null);

  // Clear hover whenever the series, symbol, or range preset changes.
  useEffect(() => {
    setHover(null);
  }, [data, rangeBars]);

  // Fixed window: the range presets upstream are the only way to change the
  // displayed time range (no wheel/drag zoom — the chart must not rescale
  // while the page scrolls).
  const full = rangeBars;
  const span = Math.max(
    MIN_SPAN,
    Math.min(Number.isFinite(full) ? full : data.length, data.length),
  );
  const end = data.length;
  const start = Math.max(0, end - span);
  const visible = useMemo(() => data.slice(start, end), [data, start, end]);

  const padL = 8;
  const padR = 76;
  const padT = 12;
  const axisH = 22;
  const volH = Math.round(height * 0.18);
  const priceH = height - padT - axisH - volH - 8;
  const plotW = Math.max(10, width - padL - padR);

  const lo = useMemo(
    () => Math.min(...visible.map((p) => p.low)),
    [visible],
  );
  const hi = useMemo(
    () => Math.max(...visible.map((p) => p.high)),
    [visible],
  );
  const pad = (hi - lo) * 0.06 || Math.max(1, hi * 0.01);
  const yMin = lo - pad;
  const yMax = hi + pad;
  const y = (v: number) => padT + (1 - (v - yMin) / (yMax - yMin)) * priceH;
  const slot = plotW / Math.max(1, visible.length);
  const x = (i: number) => padL + slot * (i + 0.5);
  const bodyW = Math.max(1, Math.min(18, slot * 0.62));

  const maxVol = Math.max(1, ...visible.map((p) => p.volume));
  const volY = (v: number) => padT + priceH + 8 + volH * (1 - v / maxVol);
  const volBase = padT + priceH + 8 + volH;

  const ticks = useMemo(() => niceTicks(yMin, yMax, 6), [yMin, yMax]);
  const labelEvery = Math.max(1, Math.ceil(visible.length / 6));

  const last = visible[visible.length - 1];

  const toIndex = (clientX: number, rectLeft: number) => {
    const px = clientX - rectLeft - padL;
    const i = Math.round(px / slot - 0.5);
    return Math.max(0, Math.min(visible.length - 1, i));
  };

  if (data.length === 0 || width < 40) {
    return <svg width={Math.max(width, 0)} height={height} role="img" aria-label="Price chart" />;
  }

  const tip = hover !== null ? visible[hover] : null;
  const tipX = hover !== null ? x(hover) : 0;
  const tipLeft = tipX > width - padR - 190;
  const tipLines = tip
    ? [
        tip.date,
        `O ₹${fmtPrice(tip.open)}   H ₹${fmtPrice(tip.high)}`,
        `L ₹${fmtPrice(tip.low)}    C ₹${fmtPrice(tip.close)}`,
        `Vol ${fmtInt(tip.volume)}`,
      ]
    : [];

  return (
    <svg
      width={width}
      height={height}
      role="img"
      aria-label={`Candlestick chart, ${visible.length} trading days`}
      onMouseMove={(e) => {
        const rect = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
        setHover(toIndex(e.clientX, rect.left));
      }}
      onMouseLeave={() => {
        setHover(null);
      }}
      style={{ cursor: 'crosshair', display: 'block' }}
    >
      {ticks.map((t) => (
        <g key={t}>
          <line x1={padL} x2={width - padR} y1={y(t)} y2={y(t)} stroke={GRID} strokeWidth={1} />
          <text x={width - padR + 6} y={y(t) + 4} fontSize={11} fill={MUTED}>
            {t.toLocaleString('en-IN', { maximumFractionDigits: 2 })}
          </text>
        </g>
      ))}
      {visible.map((p, i) =>
        i % labelEvery === 0 ? (
          <text
            key={`d-${p.date}-${i}`}
            x={x(i)}
            y={height - 6}
            fontSize={11}
            fill={MUTED}
            textAnchor="middle"
          >
            {p.date.slice(5)}
          </text>
        ) : null,
      )}
      {visible.map((p, i) => {
        const up = p.close >= p.open;
        const color = up ? UP : DOWN;
        const top = y(Math.max(p.open, p.close));
        const bottom = y(Math.min(p.open, p.close));
        return (
          <g key={`${p.date}-${i}`}>
            <rect
              x={padL + 1}
              y={volY(p.volume)}
              width={Math.max(1, slot - 2)}
              height={Math.max(0, volBase - volY(p.volume))}
              fill={color}
              opacity={0.35}
            />
            <line x1={x(i)} x2={x(i)} y1={y(p.high)} y2={y(p.low)} stroke={color} strokeWidth={1} />
            <rect
              x={x(i) - bodyW / 2}
              y={top}
              width={bodyW}
              height={Math.max(1, bottom - top)}
              fill={color}
              fillOpacity={up ? 0.25 : 1}
              stroke={color}
              strokeWidth={1}
            />
          </g>
        );
      })}
      {last && (
        <g>
          <line
            x1={padL}
            x2={width - padR}
            y1={y(last.close)}
            y2={y(last.close)}
            stroke={MUTED}
            strokeWidth={1}
            strokeDasharray="4 3"
            opacity={0.7}
          />
          <text x={width - padR + 6} y={y(last.close) + 4} fontSize={11} fill={MUTED}>
            {last.close.toLocaleString('en-IN', { maximumFractionDigits: 2 })}
          </text>
        </g>
      )}
      {tip !== null && (
        <g>
          <line
            x1={tipX}
            x2={tipX}
            y1={padT}
            y2={height - axisH}
            stroke={MUTED}
            strokeWidth={1}
            opacity={0.5}
          />
          <rect
            x={tipLeft ? tipX - 196 : tipX + 10}
            y={padT + 4}
            width={186}
            height={tipLines.length * 16 + 12}
            rx={6}
            fill={TIP_BG}
            stroke={TIP_BORDER}
            strokeWidth={1}
          />
          {tipLines.map((line, i) => (
            <text
              key={i}
              x={tipLeft ? tipX - 186 : tipX + 20}
              y={padT + 22 + i * 16}
              fontSize={11}
              fill={i === 0 ? '#e6ecf5' : MUTED}
            >
              {line}
            </text>
          ))}
        </g>
      )}
    </svg>
  );
}

export default function CandleChart({
  data,
  height = 340,
  rangeBars = Number.POSITIVE_INFINITY,
}: {
  data: MarketPricePoint[];
  height?: number;
  rangeBars?: number;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      {/* ResponsiveContainer injects measured width/height into its child. */}
      <CandleSvg data={data} width={0} height={0} rangeBars={rangeBars} />
    </ResponsiveContainer>
  );
}
