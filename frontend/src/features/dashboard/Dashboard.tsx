import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { ChartPanel } from "../../components/charts/ChartPanel";
import { ChangeText, FreshnessBadge } from "../../components/ui/primitives";
import { api } from "../../lib/api";
import { fmtNumber } from "../../lib/format";
import { mergeQuote, useLiveSubscription, useTick } from "../../lib/live";
import { useMarketOpen } from "../../lib/queries";
import { useStoredState } from "../../lib/useStoredState";
import { TIMEFRAMES, type Instrument, type Timeframe } from "../../lib/types";
import { IndexStrip } from "./IndexStrip";
import { MoversPanel, NewsPanel, SectorBoard, WatchlistPanel } from "./panels";

function ChartHeading({ instrument }: { instrument: Instrument }) {
  const marketOpen = useMarketOpen();
  useLiveSubscription([instrument.instrument_key]);
  const tick = useTick(instrument.instrument_key);
  const quotes = useQuery({ queryKey: ["indices"], queryFn: api.indices, enabled: false });
  const rest = quotes.data?.find((i) => i.instrument.instrument_key === instrument.instrument_key)?.quote;
  const q = mergeQuote(rest, tick, marketOpen);
  return (
    <span className="flex flex-wrap items-center gap-x-3 gap-y-0.5 normal-case">
      <span className="text-sm font-semibold tracking-normal text-fg">{instrument.name ?? instrument.symbol}</span>
      {q.ltp != null && (
        <>
          <span className="num text-sm text-fg">{fmtNumber(q.ltp)}</span>
          <ChangeText change={q.change} pct={q.changePct} className="text-xs" />
          <FreshnessBadge freshness={q.freshness} />
        </>
      )}
    </span>
  );
}

export function Dashboard() {
  const [params, setParams] = useSearchParams();
  const [stored, setTimeframe] = useStoredState<Timeframe>("fc-dash-tf", "15m");
  const timeframe = TIMEFRAMES.includes(stored) ? stored : "15m";
  const indices = useQuery({ queryKey: ["indices"], queryFn: api.indices });
  const requested = params.get("chart");
  const lookup = useQuery({
    queryKey: ["lookup", requested],
    queryFn: () => api.lookup(requested!),
    enabled: !!requested,
  });
  const fallback = indices.data?.[0]?.instrument;
  const instrument = (requested ? lookup.data : fallback) ?? null;

  return (
    <div className="mx-auto flex max-w-[1680px] flex-col gap-3 p-3 sm:p-4">
      <IndexStrip
        selectedKey={instrument?.instrument_key ?? null}
        onSelect={(item) => setParams({ chart: item.instrument.instrument_key }, { replace: true })}
      />
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-12">
        <div className="lg:col-span-8">
          {instrument ? (
            <ChartPanel
              instrumentKey={instrument.instrument_key}
              title={<ChartHeading instrument={instrument} />}
              timeframe={timeframe}
              onTimeframe={setTimeframe}
              showVolume={instrument.instrument_type !== "INDEX"}
              height={430}
            />
          ) : (
            <div className="flex h-[480px] items-center justify-center rounded-lg border border-line bg-surface text-sm text-muted">
              {indices.isError || lookup.isError ? "Chart unavailable until market data loads." : "Loading chart"}
            </div>
          )}
        </div>
        <WatchlistPanel limit={12} className="lg:col-span-4" />
        <MoversPanel className="lg:col-span-4" />
        <SectorBoard className="lg:col-span-4" />
        <NewsPanel className="lg:col-span-4" />
      </div>
    </div>
  );
}
