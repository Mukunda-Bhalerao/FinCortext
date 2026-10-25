import { useQuery } from "@tanstack/react-query";
import { useFlash } from "../../components/QuoteTable";
import { ChangeText, cx, ErrorState, FreshnessBadge, Skeleton } from "../../components/ui/primitives";
import { api } from "../../lib/api";
import { fmtNumber, fmtStamp } from "../../lib/format";
import { mergeQuote, useLiveSubscription, useTick } from "../../lib/live";
import { useMarketOpen } from "../../lib/queries";
import type { LabeledQuote } from "../../lib/types";

function IndexCard({
  item,
  selected,
  onSelect,
  marketOpen,
}: {
  item: LabeledQuote;
  selected: boolean;
  onSelect: () => void;
  marketOpen: boolean;
}) {
  const tick = useTick(item.instrument.instrument_key);
  const q = mergeQuote(item.quote, tick, marketOpen);
  const flash = useFlash(q.ltp);
  return (
    <button
      onClick={onSelect}
      className={cx(
        "min-w-[168px] flex-1 rounded-lg border bg-surface px-3.5 py-2.5 text-left transition-colors",
        selected ? "border-accent/60" : "border-line hover:border-line-strong",
      )}
      title={q.observedAt ? `As of ${fmtStamp(q.observedAt)} · ${q.source ?? ""}` : "No data received"}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-2xs font-semibold tracking-wide text-muted uppercase">{item.label}</span>
        <FreshnessBadge freshness={q.freshness} />
      </div>
      <div className={cx("num mt-1 rounded text-lg font-semibold text-fg", flash)}>{fmtNumber(q.ltp)}</div>
      <div className="mt-0.5 flex items-center justify-between text-xs">
        <ChangeText change={q.change} pct={q.changePct} />
        <span className="num text-2xs whitespace-nowrap text-faint">{q.observedAt ? fmtStamp(q.observedAt) : ""}</span>
      </div>
    </button>
  );
}

export function IndexStrip({
  selectedKey,
  onSelect,
}: {
  selectedKey: string | null;
  onSelect: (item: LabeledQuote) => void;
}) {
  const marketOpen = useMarketOpen();
  const q = useQuery({
    queryKey: ["indices"],
    queryFn: api.indices,
    refetchInterval: marketOpen ? 30_000 : 300_000,
  });
  useLiveSubscription((q.data ?? []).map((i) => i.instrument.instrument_key));

  if (q.isPending) {
    return (
      <div className="flex gap-3 overflow-x-auto">
        {Array.from({ length: 5 }, (_, i) => (
          <Skeleton key={i} className="h-[86px] min-w-[168px] flex-1 rounded-lg" />
        ))}
      </div>
    );
  }
  if (q.isError) {
    return (
      <div className="rounded-lg border border-line bg-surface">
        <ErrorState error={q.error} compact />
      </div>
    );
  }
  return (
    <div className="flex gap-3 overflow-x-auto pb-0.5">
      {q.data.map((item) => (
        <IndexCard
          key={item.instrument.instrument_key}
          item={item}
          marketOpen={marketOpen}
          selected={item.instrument.instrument_key === selectedKey}
          onSelect={() => onSelect(item)}
        />
      ))}
    </div>
  );
}
