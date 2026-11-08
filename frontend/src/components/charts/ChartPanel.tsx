import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api } from "../../lib/api";
import { aggregateTicks, isSeconds, SECONDS, type FeedRow } from "../../lib/chartData";
import { fmtStamp, fmtTimeIST } from "../../lib/format";
import { useLiveStatus, useTick } from "../../lib/live";
import { useMarketOpen } from "../../lib/queries";
import { CHART_TIMEFRAMES, type Candle, type ChartTimeframe, type Timeframe } from "../../lib/types";
import { cx, ErrorState, Skeleton } from "../ui/primitives";
import { PriceChart, type ChartTool, type PriceChartHandle } from "./PriceChart";

const INTRADAY: ChartTimeframe[] = ["1m", "5m", "15m", "1H"];
const NO_CANDLES: Candle[] = [];
const QUIET_MS = 15_000;

function useHLines(instrumentKey: string): [number[], (v: number[]) => void] {
  const storageKey = `fc-hlines:${instrumentKey}`;
  const read = () => {
    try {
      const v = JSON.parse(localStorage.getItem(storageKey) ?? "[]");
      return Array.isArray(v) ? v.filter((x): x is number => typeof x === "number") : [];
    } catch {
      return [];
    }
  };
  const [lines, setLines] = useState<number[]>(read);
  useEffect(() => setLines(read()), [storageKey]);
  const save = (v: number[]) => {
    setLines(v);
    try {
      localStorage.setItem(storageKey, JSON.stringify(v));
    } catch {
      /* not persisted */
    }
  };
  return [lines, save];
}

/** Re-render every second so "updated 2 s ago" stays honest. */
function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [active]);
  return now;
}

const Icon = {
  cursor: "M5 3l14 9-6 1.5L10 20z",
  zoom: "M4 4h6M4 4v6M20 20h-6M20 20v-6M9 9l6 6",
  measure: "M3 17L17 3l4 4L7 21zM7 13l2 2M10 10l2 2M13 7l2 2",
  hline: "M3 12h18M7 8v8",
  magnet: "M6 4v7a6 6 0 0012 0V4M6 4h4v7a2 2 0 004 0V4h4",
  reset: "M4 4v6h6M20 20v-6h-6M5 15a7 7 0 0012 3M19 9A7 7 0 007 6",
  expand: "M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5",
  shrink: "M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5",
  trash: "M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3",
};

function ToolButton({
  icon,
  label,
  active,
  onClick,
  disabled,
}: {
  icon: keyof typeof Icon;
  label: string;
  active?: boolean;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={label}
      aria-label={label}
      aria-pressed={active}
      className={cx(
        "flex h-6 w-6 items-center justify-center rounded transition-colors disabled:opacity-40",
        active ? "bg-accent-soft text-accent" : "text-muted hover:bg-surface-2 hover:text-fg",
      )}
    >
      <svg
        width="14"
        height="14"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden
      >
        <path d={Icon[icon]} />
      </svg>
    </button>
  );
}

function TimeframePicker({
  value,
  onChange,
  secondsAllowed,
}: {
  value: ChartTimeframe;
  onChange: (tf: ChartTimeframe) => void;
  secondsAllowed: boolean;
}) {
  return (
    <div
      className="inline-flex flex-wrap items-center rounded-md border border-line bg-surface-2 p-0.5"
      role="tablist"
      aria-label="Interval"
    >
      {CHART_TIMEFRAMES.map((t, i) => {
        const secs = isSeconds(t);
        const disabled = secs && !secondsAllowed;
        return (
          <span key={t} className="flex items-center">
            {i === 3 && <span className="mx-0.5 h-3 w-px bg-line-strong" aria-hidden />}
            <button
              role="tab"
              aria-selected={t === value}
              disabled={disabled}
              onClick={() => onChange(t)}
              title={
                secs
                  ? disabled
                    ? "Seconds candles need the live stream during market hours"
                    : `${SECONDS[t as keyof typeof SECONDS]}-second candles built from streamed updates (no history before this session)`
                  : `${t} candles from Upstox`
              }
              className={cx(
                "h-5 rounded px-1.5 text-2xs font-medium transition-colors disabled:opacity-35",
                t === value ? "bg-surface-3 text-fg" : "text-muted hover:text-fg",
                secs && "italic",
              )}
            >
              {t}
            </button>
          </span>
        );
      })}
    </div>
  );
}

export function ChartPanel({
  instrumentKey,
  title,
  timeframe,
  onTimeframe,
  showVolume,
  height = 420,
  headerExtra,
}: {
  instrumentKey: string;
  title: ReactNode;
  timeframe: ChartTimeframe;
  onTimeframe: (tf: ChartTimeframe) => void;
  showVolume: boolean;
  height?: number;
  headerExtra?: ReactNode;
}) {
  const open = useMarketOpen();
  const { status, socket } = useLiveStatus();
  const streaming = status?.transport === "stream" && status.state === "connected";
  const seconds = isSeconds(timeframe);
  const secondsAllowed = open && streaming;
  const chartRef = useRef<PriceChartHandle>(null);
  const [tool, setTool] = useState<ChartTool>("cursor");
  const [magnet, setMagnet] = useState(false);
  const [full, setFull] = useState(false);
  const [hlines, setHLines] = useHLines(instrumentKey);
  const tick = useTick(instrumentKey);

  // Fall back to a provider interval if seconds candles cannot be built right now.
  useEffect(() => {
    if (seconds && status && !secondsAllowed) onTimeframe("1m");
  }, [seconds, secondsAllowed, status, onTimeframe]);

  const provider = useQuery({
    queryKey: ["candles", instrumentKey, timeframe],
    queryFn: () => api.candles(instrumentKey, timeframe as Timeframe),
    enabled: !seconds,
    // The live feed moves the last candle; provider refreshes only correct and recover.
    refetchInterval: open ? (INTRADAY.includes(timeframe) ? 300_000 : 600_000) : false,
    refetchOnWindowFocus: false,
    placeholderData: (prev) => (prev?.instrument_key === instrumentKey ? prev : undefined),
  });
  const recorded = useQuery({
    queryKey: ["live-ticks", instrumentKey, timeframe],
    queryFn: () => api.liveTicks(instrumentKey),
    enabled: seconds,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });

  // After a socket reconnect, resynchronise from the provider (the merge keeps the view).
  const prevSocket = useRef(socket);
  useEffect(() => {
    if (prevSocket.current !== "open" && socket === "open") {
      if (seconds) void recorded.refetch();
      else void provider.refetch();
    }
    prevSocket.current = socket;
  }, [socket]);

  // Escape leaves full screen (after any tool in progress).
  useEffect(() => {
    if (!full) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && tool === "cursor") setFull(false);
      if (e.key === "Escape") setTool("cursor");
    };
    window.addEventListener("keydown", onKey);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
    };
  }, [full, tool]);

  const secondsCandles = useMemo(
    () =>
      seconds && recorded.data
        ? aggregateTicks(recorded.data.ticks as FeedRow[], SECONDS[timeframe as keyof typeof SECONDS])
        : NO_CANDLES,
    [seconds, recorded.data, timeframe],
  );
  const candles = seconds ? secondsCandles : (provider.data?.candles ?? NO_CANDLES);
  const pending = seconds ? recorded.isPending : provider.isPending;
  const error = seconds ? recorded.error : provider.error;
  const followsTicks = open && status?.state === "connected" && (seconds || !!provider.data?.candles.length);

  const now = useNow(followsTicks);
  const age = tick ? now - new Date(tick.received_at).getTime() : null;
  const quiet = followsTicks && streaming && age != null && age > QUIET_MS;
  const silent = status?.silent?.includes(instrumentKey);
  const lag = status?.latency?.provider_p50_ms;

  return (
    <section
      className={cx(
        "flex min-w-0 flex-col border border-line bg-surface",
        full ? "fixed inset-0 z-50 rounded-none p-1 sm:p-2" : "rounded-lg",
      )}
      aria-label={full ? "Chart, full screen" : undefined}
    >
      <header className="flex min-h-10 flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-line px-3.5 py-1.5">
        <h2 className="text-sm font-semibold tracking-tight text-fg">{title}</h2>
        {headerExtra && <div className="truncate text-2xs text-faint">{headerExtra}</div>}
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <TimeframePicker value={timeframe} onChange={onTimeframe} secondsAllowed={secondsAllowed} />
          <div className="flex items-center gap-0.5 rounded-md border border-line bg-surface-2 p-0.5">
            <ToolButton
              icon="cursor"
              label="Pan and inspect (drag to pan, wheel to zoom)"
              active={tool === "cursor"}
              onClick={() => setTool("cursor")}
            />
            <ToolButton
              icon="zoom"
              label="Box zoom: drag a range (or hold Shift and drag)"
              active={tool === "zoom"}
              onClick={() => setTool(tool === "zoom" ? "cursor" : "zoom")}
            />
            <ToolButton
              icon="measure"
              label="Measure: drag to see change, % and bars"
              active={tool === "measure"}
              onClick={() => setTool(tool === "measure" ? "cursor" : "measure")}
            />
            <ToolButton
              icon="hline"
              label="Horizontal line: click a price"
              active={tool === "hline"}
              onClick={() => setTool(tool === "hline" ? "cursor" : "hline")}
            />
            {hlines.length > 0 && (
              <ToolButton icon="trash" label={`Remove ${hlines.length} line(s)`} onClick={() => setHLines([])} />
            )}
            <span className="mx-0.5 h-3 w-px bg-line-strong" aria-hidden />
            <ToolButton
              icon="magnet"
              label="Magnet crosshair (snap to OHLC)"
              active={magnet}
              onClick={() => setMagnet((m) => !m)}
            />
            <ToolButton icon="reset" label="Reset view" onClick={() => chartRef.current?.resetView()} />
            <ToolButton
              icon={full ? "shrink" : "expand"}
              label={full ? "Exit full screen (Esc)" : "Full screen"}
              onClick={() => setFull((f) => !f)}
            />
          </div>
        </div>
      </header>

      <div className={cx("relative flex min-h-0 flex-col", full && "flex-1")}>
        {pending ? (
          <div className="p-3" style={{ height: full ? "100%" : height }}>
            <Skeleton className="h-full w-full" />
          </div>
        ) : error ? (
          <div style={{ height }}>
            <ErrorState error={error} />
          </div>
        ) : !seconds && candles.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-1 text-center" style={{ height }}>
            <p className="text-sm text-muted">No candles available for this timeframe.</p>
            {provider.data?.data_gaps.map((g) => (
              <p key={g} className="text-xs text-faint">
                {g}
              </p>
            ))}
          </div>
        ) : (
          <>
            <PriceChart
              ref={chartRef}
              candles={candles}
              dataKey={`${instrumentKey}@${timeframe}`}
              timeframe={timeframe}
              showVolume={showVolume}
              liveKey={followsTicks ? instrumentKey : null}
              height={full ? "fill" : height}
              tool={tool}
              magnet={magnet}
              hlines={hlines}
              onAddHLine={(p) => setHLines([...hlines, p].slice(-12))}
              onToolDone={() => setTool("cursor")}
            />
            {seconds && candles.length === 0 && (
              <p className="pointer-events-none absolute inset-x-0 top-1/2 text-center text-xs text-muted">
                Waiting for the first streamed update…
              </p>
            )}
          </>
        )}
      </div>

      <footer className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-line px-3.5 py-1.5 text-2xs text-faint">
        <span>Times in IST</span>
        {seconds ? (
          <span title="Each streamed update is a genuine last-trade price with its exchange time; prices between updates are not known, so brief highs and lows can be missed.">
            {timeframe} candles built here from {recorded.data?.count ?? 0} streamed updates
            {recorded.data?.ticks[0] ? ` since ${fmtTimeIST(recorded.data.ticks[0][0])}` : ""}; no earlier seconds
            history exists
          </span>
        ) : provider.data ? (
          <span>
            Candles: Upstox {provider.data.includes_current_session ? "historical + current session" : "historical"},
            fetched {fmtStamp(provider.data.fetched_at)}
          </span>
        ) : null}
        {followsTicks && (
          <span className={cx(streaming ? "text-up" : "text-accent", quiet && "text-caution")}>
            {streaming ? "Live" : "Polled"}
            {age != null && ` · updated ${age < 1000 ? "<1" : Math.round(age / 1000)} s ago`}
            {streaming && lag != null && ` · exchange-to-feed ~${(lag / 1000).toFixed(1)} s`}
          </span>
        )}
        {quiet && (
          <span className="text-caution">
            No update for {Math.round((age ?? 0) / 1000)} s (few trades, or the feed is delayed)
          </span>
        )}
        {silent && <span className="text-caution">The provider is not sending updates for this instrument</span>}
        {status && !streaming && open && status.state !== "connected" && (
          <span className="text-caution">Feed {status.state.replace("_", " ")}: prices may be delayed</span>
        )}
        {!open && <span>Market closed: chart shows completed data</span>}
        {provider.data?.data_gaps.map((g) => (
          <span key={g} className="text-caution">
            {g}
          </span>
        ))}
        {!seconds && provider.isFetching && !provider.isPending && <span className="ml-auto">Resyncing</span>}
      </footer>
    </section>
  );
}
