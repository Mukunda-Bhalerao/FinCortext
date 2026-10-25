import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useParams } from "react-router-dom";
import { ChartPanel } from "../../components/charts/ChartPanel";
import { useFlash } from "../../components/QuoteTable";
import { IconClose, IconInfo, IconStar } from "../../components/ui/icons";
import { ChangeText, cx, ErrorState, FreshnessBadge, Panel, Skeleton, Stat } from "../../components/ui/primitives";
import { api } from "../../lib/api";
import { fmtCompact, fmtPrice, fmtStamp } from "../../lib/format";
import { mergeQuote, useLiveStatus, useLiveSubscription, useTick } from "../../lib/live";
import { useMarketOpen } from "../../lib/queries";
import { useStoredState } from "../../lib/useStoredState";
import { TIMEFRAMES, type StockSummary, type Timeframe } from "../../lib/types";
import { AGENT_ORDER, AgentCard, CompositeSummary, isBusy, StateLabel } from "../research/agents";

function RangeBar({ low, high, value, label }: { low: number | null; high: number | null; value: number | null; label: string }) {
  const valid = low != null && high != null && value != null && high > low;
  const pos = valid ? Math.min(100, Math.max(0, ((value - low) / (high - low)) * 100)) : null;
  return (
    <div className="min-w-0">
      <div className="text-2xs tracking-wide text-faint uppercase">{label}</div>
      <div className="num mt-1 flex items-center gap-2 text-xs text-muted">
        <span>{fmtPrice(low)}</span>
        <div className="relative h-1 flex-1 rounded-full bg-surface-3">
          {pos != null && (
            <span className="absolute top-1/2 h-2.5 w-0.5 -translate-y-1/2 rounded bg-fg" style={{ left: `${pos}%` }} />
          )}
        </div>
        <span>{fmtPrice(high)}</span>
      </div>
    </div>
  );
}

function SourcesDrawer({ data, onClose }: { data: StockSummary; onClose: () => void }) {
  const { status } = useLiveStatus();
  const tick = useTick(data.instrument.instrument_key);
  const rows: [string, string][] = [
    ["Instrument key", data.instrument.instrument_key],
    ["Instrument master", "Upstox instrument file (NSE), refreshed daily"],
    ["Quote snapshot", data.quote ? `${data.quote.source}, ${fmtStamp(data.quote.fetched_at)}` : "Unavailable"],
    ["Quote state", data.quote?.freshness ?? "unavailable"],
    ["Last trade", fmtStamp(data.quote?.last_trade_time)],
    [
      "Live updates",
      status ? `${status.transport} / ${status.state}${status.detail ? ` (${status.detail})` : ""}` : "Socket not connected",
    ],
    ["Last tick received", tick ? `${fmtStamp(tick.received_at)} via ${tick.transport}` : "None yet"],
    ["Candles", "Upstox V3 historical + intraday candle API"],
    ["52-week range", data.week52_basis ?? "Unavailable"],
    ["Change basis", "Last price minus previous close reported by the provider"],
  ];
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-overlay" onClick={onClose}>
      <aside
        className="h-full w-full max-w-md overflow-y-auto border-l border-line bg-surface p-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center">
          <h2 className="text-sm font-semibold text-fg">Sources & data quality</h2>
          <button className="ml-auto text-muted hover:text-fg" onClick={onClose} aria-label="Close">
            <IconClose />
          </button>
        </div>
        <dl className="divide-y divide-line text-xs">
          {rows.map(([k, v]) => (
            <div key={k} className="grid grid-cols-[130px_1fr] gap-3 py-2">
              <dt className="text-faint">{k}</dt>
              <dd className="font-mono break-all text-muted">{v}</dd>
            </div>
          ))}
        </dl>
        <p className="mt-4 text-2xs leading-relaxed text-faint">
          Prices are for personal research and education. Tick-derived candles are replaced by provider candles on the
          next refresh. Times are shown in IST.
        </p>
      </aside>
    </div>
  );
}

function StockResearch({ symbol, inWatchlist }: { symbol: string; inWatchlist: boolean }) {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["research", symbol],
    queryFn: () => api.researchFor(symbol),
    refetchInterval: (query) => (isBusy(query.state.data) ? 3_000 : 120_000),
  });
  const run = async () => {
    await api.runResearch(symbol);
    await qc.invalidateQueries({ queryKey: ["research", symbol] });
  };
  const item = q.data;
  const report = item?.report;
  return (
    <Panel
      title="Research"
      meta={item ? <StateLabel item={item} /> : undefined}
      actions={
        item && (
          <button
            onClick={() => void run()}
            disabled={isBusy(item)}
            className="rounded-md border border-line px-2 py-0.5 text-2xs text-muted hover:border-line-strong hover:text-fg disabled:opacity-50"
          >
            {isBusy(item) ? "Running…" : report ? "Run again" : "Run research"}
          </button>
        )
      }
    >
      {q.isPending ? (
        <Skeleton className="m-3.5 h-24" />
      ) : q.isError ? (
        <ErrorState error={q.error} compact />
      ) : report ? (
        <div className="space-y-3 p-3">
          <CompositeSummary composite={report.composite} />
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 2xl:grid-cols-4">
            {AGENT_ORDER.map((name) => {
              const output = report.agents.find((a) => a.agent === name);
              return output ? <AgentCard key={name} output={output} /> : null;
            })}
          </div>
          <p className="text-2xs text-faint">
            Scores summarise the evidence shown; they are not forecasts or recommendations.
          </p>
        </div>
      ) : (
        <p className="px-3.5 py-4 text-xs text-muted">
          {isBusy(item)
            ? "The four agents are gathering data for this stock."
            : inWatchlist
              ? "Research for this stock has not run yet."
              : "Add this stock to the watchlist to keep its research current, or run it once now."}
        </p>
      )}
    </Panel>
  );
}

export function StockPage() {
  const { symbol = "" } = useParams();
  const qc = useQueryClient();
  const marketOpen = useMarketOpen();
  const [stored, setTimeframe] = useStoredState<Timeframe>("fc-stock-tf", "1D");
  const timeframe = TIMEFRAMES.includes(stored) ? stored : "1D";
  const [drawer, setDrawer] = useState(false);
  const q = useQuery({
    queryKey: ["stock", symbol],
    queryFn: () => api.stock(symbol),
    refetchInterval: marketOpen ? 30_000 : 300_000,
  });
  const key = q.data?.instrument.instrument_key;
  useLiveSubscription([key]);
  const tick = useTick(key);
  const live = mergeQuote(q.data?.quote, tick, marketOpen);
  const flash = useFlash(live.ltp);

  const toggleWatch = async () => {
    if (!q.data) return;
    if (q.data.in_watchlist) await api.unwatch(q.data.instrument.instrument_key);
    else await api.watch(q.data.instrument.instrument_key);
    await Promise.all([
      qc.invalidateQueries({ queryKey: ["stock", symbol] }),
      qc.invalidateQueries({ queryKey: ["watchlist"] }),
      qc.invalidateQueries({ queryKey: ["research"] }),
    ]);
  };

  if (q.isPending) {
    return (
      <div className="mx-auto max-w-[1680px] space-y-3 p-4">
        <Skeleton className="h-24 rounded-lg" />
        <Skeleton className="h-[480px] rounded-lg" />
      </div>
    );
  }
  if (q.isError) {
    return (
      <div className="mx-auto max-w-[1680px] p-4">
        <div className="rounded-lg border border-line bg-surface">
          <ErrorState error={q.error} />
        </div>
      </div>
    );
  }
  const d = q.data;
  const quote = d.quote;
  const high = quote?.high != null && live.ltp != null ? Math.max(quote.high, live.ltp) : quote?.high ?? null;
  const low = quote?.low != null && live.ltp != null ? Math.min(quote.low, live.ltp) : quote?.low ?? null;

  return (
    <div className="mx-auto flex max-w-[1680px] flex-col gap-3 p-3 sm:p-4">
      <section className="rounded-lg border border-line bg-surface p-4">
        <div className="flex flex-wrap items-start gap-x-8 gap-y-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-semibold tracking-tight text-fg">{d.instrument.symbol}</h1>
              <span className="rounded border border-line px-1.5 text-2xs text-muted">{d.instrument.exchange}</span>
              <button
                onClick={() => void toggleWatch()}
                className={cx("rounded p-1", d.in_watchlist ? "text-accent" : "text-faint hover:text-fg")}
                aria-label={d.in_watchlist ? "Remove from watchlist" : "Add to watchlist"}
                title={d.in_watchlist ? "In watchlist" : "Add to watchlist"}
              >
                <IconStar filled={d.in_watchlist} />
              </button>
            </div>
            <p className="mt-0.5 truncate text-sm text-muted">{d.instrument.name}</p>
            <p className="mt-0.5 text-2xs text-faint">ISIN {d.instrument.isin ?? "not listed"}</p>
          </div>
          <div>
            <div className={cx("num rounded text-2xl font-semibold text-fg", flash)}>{fmtPrice(live.ltp)}</div>
            <div className="mt-0.5 flex items-center gap-3 text-sm">
              <ChangeText change={live.change} pct={live.changePct} />
              <FreshnessBadge freshness={live.freshness} />
            </div>
            <div className="mt-0.5 text-2xs text-faint">
              {live.observedAt ? `As of ${fmtStamp(live.observedAt)}` : "No quote received"}
              {quote?.last_trade_time && ` Â· last trade ${fmtStamp(quote.last_trade_time)}`}
            </div>
          </div>
          <button
            onClick={() => setDrawer(true)}
            className="ml-auto inline-flex items-center gap-1.5 rounded-md border border-line px-2.5 py-1 text-xs text-muted hover:border-line-strong hover:text-fg"
          >
            <IconInfo width={14} height={14} /> Sources & data quality
          </button>
        </div>
        {d.problems.length > 0 && (
          <p className="mt-3 rounded-md border border-line bg-surface-2 px-3 py-2 text-xs text-muted">
            Market data unavailable: {d.problems.join(" ")}
          </p>
        )}
        <div className="mt-4 grid grid-cols-2 gap-x-6 gap-y-3 border-t border-line pt-3 sm:grid-cols-4 lg:grid-cols-8">
          <Stat label="Open" value={fmtPrice(quote?.open)} />
          <Stat label="High" value={fmtPrice(high)} />
          <Stat label="Low" value={fmtPrice(low)} />
          <Stat label="Prev close" value={fmtPrice(live.prevClose)} />
          <Stat label="Volume" value={fmtCompact(live.volume)} />
          <Stat label="Avg price" value={fmtPrice(quote?.avg_price)} sub="Volume weighted" />
          <Stat label="Upper circuit" value={fmtPrice(quote?.upper_circuit)} />
          <Stat label="Lower circuit" value={fmtPrice(quote?.lower_circuit)} />
        </div>
        <div className="mt-3 grid grid-cols-1 gap-x-8 gap-y-3 sm:grid-cols-2">
          <RangeBar label="Day range" low={low} high={high} value={live.ltp} />
          <RangeBar label="52-week range" low={d.week52_low} high={d.week52_high} value={live.ltp} />
        </div>
      </section>

      <ChartPanel
        instrumentKey={d.instrument.instrument_key}
        title="Price"
        timeframe={timeframe}
        onTimeframe={setTimeframe}
        showVolume
        height={460}
      />

      <StockResearch symbol={d.instrument.symbol} inWatchlist={d.in_watchlist} />

      {drawer && <SourcesDrawer data={d} onClose={() => setDrawer(false)} />}
    </div>
  );
}
