import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useRef, useState } from "react";
import { fmtCompact, fmtNumber } from "../../lib/format";
import { applyTick, type LiveCandleState } from "../../lib/liveCandle";
import { useTick } from "../../lib/live";
import type { Candle, CandleSeries, Timeframe } from "../../lib/types";

// lightweight-charts renders timestamps as UTC. Shifting by the IST offset makes the
// axis and crosshair read in IST; data stays UTC everywhere else.
const IST_OFFSET = 19800;
const toChartTime = (t: number) => (t + IST_OFFSET) as UTCTimestamp;

function token(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function palette() {
  return {
    text: token("--text-muted"),
    grid: token("--chart-grid"),
    border: token("--border"),
    up: token("--up"),
    down: token("--down"),
    upSoft: token("--volume-up"),
    downSoft: token("--volume-down"),
    bg: token("--surface"),
  };
}

const priceFormatter = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

interface Props {
  series: CandleSeries;
  showVolume: boolean;
  /** When set, the last candle follows live ticks for this instrument. */
  liveKey?: string | null;
  height?: number;
}

export function PriceChart({ series, showVolume, liveKey, height = 420 }: Props) {
  const el = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const candleSeries = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeSeries = useRef<ISeriesApi<"Histogram"> | null>(null);
  const last = useRef<Candle | undefined>(undefined);
  const liveState = useRef<LiveCandleState>({ lastVolume: null });
  const byTime = useRef(new Map<number, Candle>());
  const [hover, setHover] = useState<Candle | undefined>(undefined);
  const [lastShown, setLastShown] = useState<Candle | undefined>(undefined);
  const tick = useTick(liveKey);

  useEffect(() => {
    if (!el.current) return;
    const p = palette();
    const c = createChart(el.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: p.text,
        fontFamily: getComputedStyle(document.body).fontFamily,
        fontSize: 11,
        attributionLogo: false,
      },
      grid: { vertLines: { color: p.grid }, horzLines: { color: p.grid } },
      rightPriceScale: { borderColor: p.border },
      timeScale: { borderColor: p.border, rightOffset: 4, minBarSpacing: 1 },
      crosshair: { mode: CrosshairMode.Normal },
      localization: { priceFormatter: (v: number) => priceFormatter.format(v) },
    });
    const cs = c.addSeries(CandlestickSeries, {
      upColor: p.up,
      downColor: p.down,
      wickUpColor: p.up,
      wickDownColor: p.down,
      borderVisible: false,
      priceLineWidth: 1,
    });
    cs.priceScale().applyOptions({ scaleMargins: { top: 0.06, bottom: 0.24 } });
    const vs = c.addSeries(HistogramSeries, {
      priceScaleId: "volume",
      priceFormat: { type: "volume" },
      lastValueVisible: false,
      priceLineVisible: false,
    });
    vs.priceScale().applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
    c.subscribeCrosshairMove((param) => {
      if (param.time === undefined) return setHover(undefined);
      setHover(byTime.current.get((param.time as number) - IST_OFFSET));
    });
    chart.current = c;
    candleSeries.current = cs;
    volumeSeries.current = vs;

    const observer = new MutationObserver(() => {
      const q = palette();
      c.applyOptions({
        layout: { textColor: q.text },
        grid: { vertLines: { color: q.grid }, horzLines: { color: q.grid } },
        rightPriceScale: { borderColor: q.border },
        timeScale: { borderColor: q.border },
      });
      cs.applyOptions({ upColor: q.up, downColor: q.down, wickUpColor: q.up, wickDownColor: q.down });
    });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => {
      observer.disconnect();
      c.remove();
      chart.current = null;
    };
  }, []);

  useEffect(() => {
    const cs = candleSeries.current;
    const vs = volumeSeries.current;
    if (!cs || !vs) return;
    const p = palette();
    const intraday = ["1m", "5m", "15m", "1H"].includes(series.timeframe);
    chart.current?.applyOptions({ timeScale: { timeVisible: intraday, secondsVisible: false } });
    cs.setData(
      series.candles.map((c) => ({ time: toChartTime(c.time), open: c.open, high: c.high, low: c.low, close: c.close })),
    );
    vs.setData(
      showVolume
        ? series.candles.map((c) => ({
            time: toChartTime(c.time),
            value: c.volume,
            color: c.close >= c.open ? p.upSoft : p.downSoft,
          }))
        : [],
    );
    byTime.current = new Map(series.candles.map((c) => [c.time, c]));
    last.current = series.candles.at(-1);
    setLastShown(last.current);
    liveState.current = { lastVolume: null };
    chart.current?.timeScale().fitContent();
    if (series.candles.length > 180) {
      chart.current?.timeScale().setVisibleLogicalRange({ from: series.candles.length - 180, to: series.candles.length + 4 });
    }
  }, [series, showVolume]);

  useEffect(() => {
    if (!tick || !liveKey) return;
    const next = applyTick(last.current, tick, series.timeframe as Timeframe, liveState.current);
    if (!next) return;
    const p = palette();
    candleSeries.current?.update({
      time: toChartTime(next.time),
      open: next.open,
      high: next.high,
      low: next.low,
      close: next.close,
    });
    if (showVolume) {
      volumeSeries.current?.update({
        time: toChartTime(next.time),
        value: next.volume,
        color: next.close >= next.open ? p.upSoft : p.downSoft,
      });
    }
    byTime.current.set(next.time, next);
    last.current = next;
    setLastShown(next);
  }, [tick, liveKey, series.timeframe, showVolume]);

  const shown = hover ?? lastShown;
  return (
    <div className="relative" style={{ height }}>
      {shown && (
        <div className="num pointer-events-none absolute top-1.5 left-2 z-10 flex flex-wrap gap-x-3 text-2xs text-muted">
          <span>
            O <span className="text-fg">{fmtNumber(shown.open)}</span>
          </span>
          <span>
            H <span className="text-fg">{fmtNumber(shown.high)}</span>
          </span>
          <span>
            L <span className="text-fg">{fmtNumber(shown.low)}</span>
          </span>
          <span>
            C <span className={shown.close >= shown.open ? "text-up" : "text-down"}>{fmtNumber(shown.close)}</span>
          </span>
          {showVolume && (
            <span>
              Vol <span className="text-fg">{fmtCompact(shown.volume)}</span>
            </span>
          )}
        </div>
      )}
      <div ref={el} className="absolute inset-0" />
    </div>
  );
}
