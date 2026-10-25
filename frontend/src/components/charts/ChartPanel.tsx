import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { api } from "../../lib/api";
import { fmtStamp } from "../../lib/format";
import { useLiveStatus } from "../../lib/live";
import { useMarketOpen } from "../../lib/queries";
import { TIMEFRAMES, type Timeframe } from "../../lib/types";
import { ErrorState, Panel, Segmented, Skeleton } from "../ui/primitives";
import { PriceChart } from "./PriceChart";

const INTRADAY: Timeframe[] = ["1m", "5m", "15m", "1H"];

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
  timeframe: Timeframe;
  onTimeframe: (tf: Timeframe) => void;
  showVolume: boolean;
  height?: number;
  headerExtra?: ReactNode;
}) {
  const open = useMarketOpen();
  const { status } = useLiveStatus();
  const q = useQuery({
    queryKey: ["candles", instrumentKey, timeframe],
    queryFn: () => api.candles(instrumentKey, timeframe),
    // Provider candles replace any tick-derived candle periodically while the market is open.
    refetchInterval: open ? (INTRADAY.includes(timeframe) ? 60_000 : 300_000) : false,
    placeholderData: (prev) => (prev?.instrument_key === instrumentKey ? prev : undefined),
  });
  const streaming = status?.transport === "stream" && status.state === "connected";
  const followsTicks = open && (status?.state === "connected") && !!q.data?.candles.length;

  return (
    <Panel
      title={title}
      meta={headerExtra}
      actions={
        <Segmented
          value={timeframe}
          onChange={onTimeframe}
          options={TIMEFRAMES.map((t) => ({ value: t, label: t }))}
          size="xs"
        />
      }
    >
      {q.isPending ? (
        <div className="p-3" style={{ height }}>
          <Skeleton className="h-full w-full" />
        </div>
      ) : q.isError ? (
        <div style={{ height }}>
          <ErrorState error={q.error} />
        </div>
      ) : q.data.candles.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-1 text-center" style={{ height }}>
          <p className="text-sm text-muted">No candles available for this timeframe.</p>
          {q.data.data_gaps.map((g) => (
            <p key={g} className="text-xs text-faint">
              {g}
            </p>
          ))}
        </div>
      ) : (
        <>
          <PriceChart series={q.data} showVolume={showVolume} liveKey={followsTicks ? instrumentKey : null} height={height} />
          <footer className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-line px-3.5 py-1.5 text-2xs text-faint">
            <span>Times in IST</span>
            <span>
              Candles: Upstox historical {q.data.includes_current_session ? "+ current session" : ""}, fetched{" "}
              {fmtStamp(q.data.fetched_at)}
            </span>
            {followsTicks && (
              <span className={streaming ? "text-up" : "text-accent"}>
                Last candle follows {streaming ? "streamed" : "polled"} trades
              </span>
            )}
            {!open && <span>Market closed: chart shows completed data</span>}
            {q.data.data_gaps.map((g) => (
              <span key={g} className="text-caution">
                {g}
              </span>
            ))}
            {q.isFetching && <span className="ml-auto">Refreshing</span>}
          </footer>
        </>
      )}
    </Panel>
  );
}
