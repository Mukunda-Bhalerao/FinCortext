import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineStyle,
  createChart,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type Logical,
  type UTCTimestamp,
} from "lightweight-charts";
import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from "react";
import { planRefresh } from "../../lib/chartData";
import { fmtCompact, fmtNumber } from "../../lib/format";
import { applyTick, type LiveCandleState } from "../../lib/liveCandle";
import { useTick } from "../../lib/live";
import type { Candle, ChartTimeframe } from "../../lib/types";
import { cx } from "../ui/primitives";

// lightweight-charts renders timestamps as UTC. Shifting by the IST offset makes the
// axis and crosshair read in IST; data stays UTC everywhere else.
const IST_OFFSET = 19800;
const toChartTime = (t: number) => (t + IST_OFFSET) as UTCTimestamp;
const DEFAULT_BARS = 120;
const RIGHT_OFFSET = 6;

export type ChartTool = "cursor" | "zoom" | "measure" | "hline";

export interface PriceChartHandle {
  resetView(): void;
  goLatest(): void;
}

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
    accent: token("--accent"),
  };
}

const priceFormatter = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

interface Props {
  candles: Candle[];
  /** Identity of the data (instrument and timeframe); a change starts a fresh view. */
  dataKey: string;
  timeframe: ChartTimeframe;
  showVolume: boolean;
  /** When set, the last candle follows live ticks for this instrument. */
  liveKey?: string | null;
  height?: number | "fill";
  tool?: ChartTool;
  magnet?: boolean;
  hlines?: number[];
  onAddHLine?: (price: number) => void;
  onToolDone?: () => void;
}

interface Drag {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
  mode: "zoom" | "measure";
  done: boolean;
}

export const PriceChart = forwardRef<PriceChartHandle, Props>(function PriceChart(
  {
    candles,
    dataKey,
    timeframe,
    showVolume,
    liveKey,
    height = 420,
    tool = "cursor",
    magnet = false,
    hlines = [],
    onAddHLine,
    onToolDone,
  },
  ref,
) {
  const el = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const candleSeries = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeSeries = useRef<ISeriesApi<"Histogram"> | null>(null);
  const shown = useRef<Candle[]>([]);
  const index = useRef(new Map<number, number>());
  const appliedKey = useRef<string | null>(null);
  const liveState = useRef<LiveCandleState>({ lastVolume: null });
  const priceLines = useRef<IPriceLine[]>([]);
  const volumeOn = useRef(showVolume);
  const [hover, setHover] = useState<number | undefined>(undefined);
  const [version, setVersion] = useState(0); // bumps when the last candle changes, for the legend
  const [away, setAway] = useState(false);
  const [shift, setShift] = useState(false);
  const [drag, setDragState] = useState<Drag | null>(null);
  // Handlers read the drag from a ref: mouse events can arrive faster than React re-renders.
  const dragRef = useRef<Drag | null>(null);
  const setDrag = (d: Drag | null) => {
    dragRef.current = d;
    setDragState(d);
  };
  const tick = useTick(liveKey);
  volumeOn.current = showVolume;

  const volumeBar = (c: Candle, p = palette()) => ({
    time: toChartTime(c.time),
    value: c.volume,
    color: c.close >= c.open ? p.upSoft : p.downSoft,
  });
  const candleBar = (c: Candle) => ({
    time: toChartTime(c.time),
    open: c.open,
    high: c.high,
    low: c.low,
    close: c.close,
  });

  const defaultView = useCallback(() => {
    const ts = chart.current?.timeScale();
    const n = shown.current.length;
    if (!ts || !n) return;
    candleSeries.current?.priceScale().setAutoScale(true);
    if (n > DEFAULT_BARS) {
      ts.setVisibleLogicalRange({ from: n - DEFAULT_BARS, to: n - 1 + RIGHT_OFFSET });
    } else {
      ts.fitContent();
    }
  }, []);

  useImperativeHandle(
    ref,
    () => ({
      resetView: defaultView,
      goLatest: () => {
        candleSeries.current?.priceScale().setAutoScale(true);
        chart.current?.timeScale().scrollToRealTime();
      },
    }),
    [defaultView],
  );

  // --- chart instance (created once) -------------------------------------------------------
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
      timeScale: {
        borderColor: p.border,
        rightOffset: RIGHT_OFFSET,
        minBarSpacing: 0.5,
        // New bars move the view only when the latest bar is already on screen.
        shiftVisibleRangeOnNewBar: true,
        // Resizing (full screen, sidebar, window) keeps the same time window on screen.
        lockVisibleTimeRangeOnResize: true,
      },
      crosshair: { mode: CrosshairMode.Normal },
      localization: { priceFormatter: (v: number) => priceFormatter.format(v) },
      handleScale: { axisPressedMouseMove: { time: true, price: true }, mouseWheel: true, pinch: true },
      handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
    });
    const cs = c.addSeries(CandlestickSeries, {
      upColor: p.up,
      downColor: p.down,
      wickUpColor: p.up,
      wickDownColor: p.down,
      borderVisible: false,
      priceLineWidth: 1,
    });
    cs.priceScale().applyOptions({ scaleMargins: { top: 0.08, bottom: 0.24 } });
    const vs = c.addSeries(HistogramSeries, {
      priceScaleId: "volume",
      priceFormat: { type: "volume" },
      lastValueVisible: false,
      priceLineVisible: false,
    });
    vs.priceScale().applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
    c.subscribeCrosshairMove((param) => {
      setHover(param.time === undefined ? undefined : (param.time as number) - IST_OFFSET);
    });
    c.timeScale().subscribeVisibleLogicalRangeChange((range) => {
      const n = shown.current.length;
      setAway(!!range && n > 0 && range.to < n - 1.5);
    });
    chart.current = c;
    candleSeries.current = cs;
    volumeSeries.current = vs;
    if (import.meta.env.DEV) {
      // Test hook (development builds only): inspect charts from the browser console.
      const w = window as unknown as { __fcCharts?: Map<HTMLElement, IChartApi> };
      (w.__fcCharts ??= new Map()).set(el.current, c);
    }

    const observer = new MutationObserver(() => {
      const q = palette();
      c.applyOptions({
        layout: { textColor: q.text },
        grid: { vertLines: { color: q.grid }, horzLines: { color: q.grid } },
        rightPriceScale: { borderColor: q.border },
        timeScale: { borderColor: q.border },
      });
      cs.applyOptions({ upColor: q.up, downColor: q.down, wickUpColor: q.up, wickDownColor: q.down });
      if (volumeOn.current) vs.setData(shown.current.map((x) => volumeBar(x, q)));
      priceLines.current.forEach((l) => l.applyOptions({ color: q.accent }));
    });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    const host = el.current;
    return () => {
      observer.disconnect();
      if (import.meta.env.DEV)
        (window as unknown as { __fcCharts?: Map<HTMLElement, IChartApi> }).__fcCharts?.delete(host);
      c.remove();
      chart.current = null;
      candleSeries.current = null;
      volumeSeries.current = null;
      priceLines.current = [];
      appliedKey.current = null;
    };
  }, []);

  // --- data: fresh view on a new key, in-place merge on refresh ------------------------------
  useEffect(() => {
    const c = chart.current;
    const cs = candleSeries.current;
    const vs = volumeSeries.current;
    if (!c || !cs || !vs) return;
    const ts = c.timeScale();
    const seconds = typeof timeframe === "string" && timeframe.endsWith("s");
    c.applyOptions({
      timeScale: { timeVisible: seconds || ["1m", "5m", "15m", "1H"].includes(timeframe), secondsVisible: seconds },
    });
    const setAll = (list: Candle[]) => {
      cs.setData(list.map(candleBar));
      vs.setData(showVolume ? list.map((x) => volumeBar(x)) : []);
      shown.current = list;
      index.current = new Map(list.map((x, i) => [x.time, i]));
    };

    if (appliedKey.current !== dataKey) {
      // New instrument or timeframe. Keep the same time window when switching timeframe on
      // the same instrument if it still holds a sensible number of the new bars.
      const prevKey = appliedKey.current;
      const sameInstrument = prevKey?.split("@")[0] === dataKey.split("@")[0];
      const prevRange = sameInstrument && shown.current.length ? ts.getVisibleRange() : null;
      appliedKey.current = dataKey;
      liveState.current = { lastVolume: null };
      setAll(candles);
      if (prevRange) {
        const from = (prevRange.from as number) - IST_OFFSET;
        const to = (prevRange.to as number) - IST_OFFSET;
        const inside = candles.filter((x) => x.time >= from && x.time <= to).length;
        if (inside >= 20) {
          ts.setVisibleRange({ from: prevRange.from, to: prevRange.to });
        } else defaultView();
      } else defaultView();
      setVersion((v) => v + 1);
      return;
    }

    const plan = planRefresh(shown.current, candles);
    if (plan.mode === "none") return;
    if (plan.mode === "tail") {
      for (let i = plan.from; i < plan.candles.length; i++) {
        const bar = plan.candles[i]!;
        cs.update(candleBar(bar));
        if (showVolume) vs.update(volumeBar(bar));
        index.current.set(bar.time, i);
      }
      shown.current = plan.candles;
    } else {
      // Older bars changed: replace the data but put the view back exactly where it was.
      const n0 = shown.current.length;
      const logical = ts.getVisibleLogicalRange();
      const atEdge = !!logical && logical.to >= n0 - 1.5;
      const range = ts.getVisibleRange();
      setAll(plan.candles);
      const n = plan.candles.length;
      if (atEdge && logical) {
        const width = logical.to - logical.from;
        const right = logical.to - (n0 - 1);
        ts.setVisibleLogicalRange({ from: (n - 1 + right - width) as Logical, to: (n - 1 + right) as Logical });
      } else if (range) {
        ts.setVisibleRange(range);
      }
    }
    setVersion((v) => v + 1);
  }, [candles, dataKey, showVolume, timeframe, defaultView]);

  // --- live ticks: update the last candle or append one --------------------------------------
  useEffect(() => {
    if (!tick || !liveKey || appliedKey.current !== dataKey) return;
    const last = shown.current[shown.current.length - 1];
    const next = applyTick(last, tick, timeframe, liveState.current);
    if (!next) return;
    candleSeries.current?.update(candleBar(next));
    if (showVolume) volumeSeries.current?.update(volumeBar(next));
    if (last && next.time === last.time) {
      shown.current = [...shown.current.slice(0, -1), next];
    } else {
      shown.current = [...shown.current, next];
      index.current.set(next.time, shown.current.length - 1);
      if (shown.current.length === 1) defaultView();
    }
    setVersion((v) => v + 1);
  }, [tick, liveKey, timeframe, showVolume, dataKey, defaultView]);

  // --- crosshair mode and horizontal lines --------------------------------------------------
  useEffect(() => {
    chart.current?.applyOptions({ crosshair: { mode: magnet ? CrosshairMode.Magnet : CrosshairMode.Normal } });
  }, [magnet]);

  useEffect(() => {
    const cs = candleSeries.current;
    if (!cs) return;
    priceLines.current.forEach((l) => cs.removePriceLine(l));
    const color = token("--accent");
    priceLines.current = hlines.map((price) =>
      cs.createPriceLine({
        price,
        color,
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: "",
      }),
    );
  }, [hlines]);

  // --- drag tools: box zoom (tool or Shift+drag) and measure ---------------------------------
  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (e.key === "Shift") setShift(true);
      if (e.key === "Escape") setDrag(null);
    };
    const up = (e: KeyboardEvent) => e.key === "Shift" && setShift(false);
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
    };
  }, []);

  const overlayActive = tool !== "cursor" || shift;
  const point = (e: React.MouseEvent) => {
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  };
  const onDown = (e: React.MouseEvent) => {
    if (e.button !== 0) return;
    const { x, y } = point(e);
    if (tool === "hline") {
      const price = candleSeries.current?.coordinateToPrice(y);
      if (price != null) onAddHLine?.(Math.round(price * 100) / 100);
      onToolDone?.();
      return;
    }
    setDrag({ x0: x, y0: y, x1: x, y1: y, mode: tool === "measure" ? "measure" : "zoom", done: false });
  };
  const onMove = (e: React.MouseEvent) => {
    const drag = dragRef.current;
    if (!drag || drag.done) return;
    const { x, y } = point(e);
    setDrag({ ...drag, x1: x, y1: y });
  };
  const onUp = (e: React.MouseEvent) => {
    const current = dragRef.current;
    if (!current || current.done) return;
    const end = point(e);
    const drag = { ...current, x1: end.x, y1: end.y };
    const ts = chart.current?.timeScale();
    const cs = candleSeries.current;
    if (drag.mode === "zoom") {
      setDrag(null);
      if (ts && cs && Math.abs(drag.x1 - drag.x0) > 8) {
        const a = ts.coordinateToLogical(Math.min(drag.x0, drag.x1));
        const b = ts.coordinateToLogical(Math.max(drag.x0, drag.x1));
        if (a != null && b != null && b - a >= 2) ts.setVisibleLogicalRange({ from: a, to: b });
        if (Math.abs(drag.y1 - drag.y0) > 8) {
          const p1 = cs.coordinateToPrice(drag.y0);
          const p2 = cs.coordinateToPrice(drag.y1);
          if (p1 != null && p2 != null) {
            cs.priceScale().setVisibleRange({ from: Math.min(p1, p2), to: Math.max(p1, p2) });
          }
        }
      }
      if (tool === "zoom") onToolDone?.();
    } else {
      setDrag({ ...drag, done: true });
    }
  };

  // --- legend ------------------------------------------------------------------------------
  void version;
  const list = shown.current;
  const i = hover !== undefined ? index.current.get(hover) : list.length - 1;
  const bar = i !== undefined ? list[i] : undefined;
  const prev = i !== undefined && i > 0 ? list[i - 1] : undefined;
  const chg = bar && prev ? bar.close - prev.close : null;

  let measure: { left: number; top: number; w: number; h: number; text: string; up: boolean } | null = null;
  if (drag) {
    const left = Math.min(drag.x0, drag.x1);
    const top = Math.min(drag.y0, drag.y1);
    let text = "";
    let up = true;
    if (drag.mode === "measure") {
      const cs = candleSeries.current;
      const ts = chart.current?.timeScale();
      const p0 = cs?.coordinateToPrice(drag.y0);
      const p1 = cs?.coordinateToPrice(drag.y1);
      const l0 = ts?.coordinateToLogical(drag.x0);
      const l1 = ts?.coordinateToLogical(drag.x1);
      if (p0 != null && p1 != null) {
        const d = p1 - p0;
        up = d >= 0;
        const bars = l0 != null && l1 != null ? Math.round(Math.abs(l1 - l0)) : 0;
        text = `${d >= 0 ? "+" : "−"}${fmtNumber(Math.abs(d))} (${d >= 0 ? "+" : "−"}${fmtNumber(Math.abs((d / p0) * 100))}%) · ${bars} bars`;
      }
    }
    measure = { left, top, w: Math.abs(drag.x1 - drag.x0), h: Math.abs(drag.y1 - drag.y0), text, up };
  }

  return (
    <div
      className={cx("relative", height === "fill" && "h-full min-h-0 flex-1")}
      style={height === "fill" ? undefined : { height }}
    >
      {bar && (
        <div className="num pointer-events-none absolute top-1.5 left-2 z-10 flex flex-wrap gap-x-3 gap-y-0.5 text-2xs text-muted">
          <span>
            O <span className="text-fg">{fmtNumber(bar.open)}</span>
          </span>
          <span>
            H <span className="text-fg">{fmtNumber(bar.high)}</span>
          </span>
          <span>
            L <span className="text-fg">{fmtNumber(bar.low)}</span>
          </span>
          <span>
            C <span className={bar.close >= bar.open ? "text-up" : "text-down"}>{fmtNumber(bar.close)}</span>
          </span>
          {chg != null && prev && (
            <span className={chg >= 0 ? "text-up" : "text-down"}>
              {chg >= 0 ? "+" : "−"}
              {fmtNumber(Math.abs(chg))} ({chg >= 0 ? "+" : "−"}
              {fmtNumber(Math.abs((chg / prev.close) * 100))}%)
            </span>
          )}
          {showVolume && (
            <span>
              Vol <span className="text-fg">{fmtCompact(bar.volume)}</span>
            </span>
          )}
        </div>
      )}
      <div ref={el} className="absolute inset-0" />
      <div
        className={cx("absolute inset-0 z-[5]", overlayActive ? "pointer-events-auto" : "pointer-events-none")}
        style={{ cursor: tool === "hline" ? "row-resize" : overlayActive ? "crosshair" : undefined }}
        onMouseDown={overlayActive ? onDown : undefined}
        onMouseMove={overlayActive ? onMove : undefined}
        onMouseUp={overlayActive ? onUp : undefined}
        onMouseLeave={() => dragRef.current && !dragRef.current.done && setDrag(null)}
        aria-hidden
      >
        {measure && (
          <div
            className={cx(
              "absolute border",
              drag?.mode === "zoom"
                ? "border-accent bg-accent-soft"
                : measure.up
                  ? "border-up/60 bg-up-soft"
                  : "border-down/60 bg-down-soft",
            )}
            style={{ left: measure.left, top: measure.top, width: measure.w, height: measure.h }}
          >
            {measure.text && (
              <span className="num absolute -top-6 left-0 rounded bg-surface-3 px-1.5 py-0.5 text-2xs whitespace-nowrap text-fg shadow">
                {measure.text}
              </span>
            )}
          </div>
        )}
      </div>
      {away && (
        <button
          onClick={() => {
            candleSeries.current?.priceScale().setAutoScale(true);
            chart.current?.timeScale().scrollToRealTime();
          }}
          className="absolute right-16 bottom-9 z-10 flex items-center gap-1 rounded-md border border-line-strong bg-surface px-2 py-1 text-2xs font-medium text-fg shadow hover:border-accent hover:text-accent"
          title="Scroll to the latest candle"
        >
          Latest
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
            <path d="M5 12h14M13 6l6 6-6 6" />
          </svg>
        </button>
      )}
    </div>
  );
});
