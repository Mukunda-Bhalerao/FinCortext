import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { fmtCompact, fmtNumber, fmtPrice, fmtStamp } from "../lib/format";
import { mergeQuote, useLiveSubscription, useTick } from "../lib/live";
import { useMarketOpen } from "../lib/queries";
import type { LabeledQuote } from "../lib/types";
import { instrumentPath } from "./SearchBox";
import { ChangeText, cx, FreshnessBadge } from "./ui/primitives";
import { Sparkline, StockAvatar } from "./ui/visual";
import { useSparklines } from "../lib/sparklines";

/** Returns a CSS class that briefly highlights a value when it moves. */
export function useFlash(value: number | null | undefined): string {
  const prev = useRef(value);
  const [cls, setCls] = useState("");
  useEffect(() => {
    if (value != null && prev.current != null && value !== prev.current) {
      setCls(value > prev.current ? "fc-flash-up" : "fc-flash-down");
      const t = setTimeout(() => setCls(""), 900);
      prev.current = value;
      return () => clearTimeout(t);
    }
    prev.current = value;
    return undefined;
  }, [value]);
  return cls;
}

/** The trend line ends at today's live price when the market has moved since the last close. */
function live(points: number[] | undefined, ltp: number | null): number[] | undefined {
  if (!points?.length || ltp == null) return points;
  return Math.abs(points[points.length - 1]! - ltp) > 1e-9 ? [...points.slice(1), ltp] : points;
}

type SortKey = "symbol" | "ltp" | "change_pct" | "volume";

interface Column {
  key: SortKey;
  label: string;
  align: "left" | "right";
}

function Row({
  item,
  showVolume,
  showName,
  marketOpen,
  trailing,
  spark,
}: {
  item: LabeledQuote;
  showVolume: boolean;
  showName: boolean;
  marketOpen: boolean;
  trailing?: (item: LabeledQuote) => ReactNode;
  spark?: number[];
}) {
  const navigate = useNavigate();
  const tick = useTick(item.instrument.instrument_key);
  const q = mergeQuote(item.quote, tick, marketOpen);
  const flash = useFlash(q.ltp);
  const isIndex = item.instrument.instrument_type === "INDEX";
  return (
    <tr
      className="group cursor-pointer border-b border-line/60 last:border-0 hover:bg-surface-2"
      onClick={() => navigate(instrumentPath(item.instrument))}
    >
      <td className="max-w-0 py-1.5 pr-2 pl-3.5">
        <div className="flex min-w-0 items-center gap-2.5">
          <StockAvatar symbol={item.label} size={28} />
          <div className="min-w-0">
            <div className="truncate text-sm font-medium text-fg group-hover:text-accent">{item.label}</div>
            {showName && <div className="truncate text-2xs text-faint">{item.instrument.name}</div>}
          </div>
        </div>
      </td>
      <td className="hidden py-1.5 pr-2 sm:table-cell">
        <Sparkline points={live(spark, q.ltp)} width={64} height={20} className="ml-auto block" />
      </td>
      <td className={cx("num py-1.5 pr-2 text-right text-sm text-fg", flash)}>
        {isIndex ? fmtNumber(q.ltp) : fmtPrice(q.ltp)}
      </td>
      <td className="py-1.5 pr-2 text-right text-xs">
        <ChangeText change={q.change} pct={q.changePct} showAbs={false} />
      </td>
      {showVolume && <td className="num py-1.5 pr-2 text-right text-xs text-muted">{fmtCompact(q.volume)}</td>}
      <td className="w-px py-1.5 pr-3.5 text-right whitespace-nowrap">
        {trailing ? (
          trailing(item)
        ) : (
          <span title={q.observedAt ? `As of ${fmtStamp(q.observedAt)} · ${q.source ?? ""}` : undefined}>
            <FreshnessBadge freshness={q.freshness} />
          </span>
        )}
      </td>
    </tr>
  );
}

export function QuoteTable({
  items,
  showVolume = false,
  showName = true,
  sortable = false,
  trailing,
  trailingLabel = "",
}: {
  items: LabeledQuote[];
  showVolume?: boolean;
  showName?: boolean;
  sortable?: boolean;
  trailing?: (item: LabeledQuote) => ReactNode;
  trailingLabel?: string;
}) {
  const marketOpen = useMarketOpen();
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 } | null>(null);
  useLiveSubscription(items.map((i) => i.instrument.instrument_key));
  const sparks = useSparklines(items.map((i) => i.instrument.instrument_key));

  const sorted = useMemo(() => {
    if (!sort) return items;
    const val = (i: LabeledQuote): number | string =>
      sort.key === "symbol" ? i.label : (i.quote?.[sort.key] ?? Number.NEGATIVE_INFINITY);
    return [...items].sort((a, b) => {
      const x = val(a);
      const y = val(b);
      return (x < y ? -1 : x > y ? 1 : 0) * sort.dir;
    });
  }, [items, sort]);

  const columns: Column[] = [
    { key: "symbol", label: "Symbol", align: "left" },
    { key: "ltp", label: "Price", align: "right" },
    { key: "change_pct", label: "Change", align: "right" },
    ...(showVolume ? [{ key: "volume" as const, label: "Volume", align: "right" as const }] : []),
  ];

  return (
    <table className="w-full table-fixed border-collapse">
      <colgroup>
        <col />
        <col className="hidden w-[76px] sm:table-column" />
        <col className="w-[26%]" />
        <col className="w-[22%]" />
        {showVolume && <col className="w-[16%]" />}
        <col className="w-[88px]" />
      </colgroup>
      <thead>
        <tr className="border-b border-line text-2xs tracking-wide text-faint uppercase">
          {columns.slice(0, 1).map((c) => (
            <th
              key={c.key}
              className={cx(
                "py-1.5 pl-3.5 text-left font-medium",
                sortable && "cursor-pointer select-none hover:text-muted",
              )}
              onClick={
                sortable
                  ? () =>
                      setSort((s) =>
                        s?.key === c.key ? (s.dir === -1 ? { key: c.key, dir: 1 } : null) : { key: c.key, dir: -1 },
                      )
                  : undefined
              }
            >
              {c.label}
              {sort?.key === c.key && <span className="ml-0.5">{sort.dir === 1 ? "↑" : "↓"}</span>}
            </th>
          ))}
          <th className="hidden pr-2 text-right font-medium sm:table-cell">1M</th>
          {columns.slice(1).map((c) => (
            <th
              key={c.key}
              className={cx(
                "py-1.5 font-medium",
                c.align === "left" ? "pl-3.5 text-left" : "pr-2 text-right",
                sortable && "cursor-pointer select-none hover:text-muted",
              )}
              onClick={
                sortable
                  ? () =>
                      setSort((s) =>
                        s?.key === c.key ? (s.dir === -1 ? { key: c.key, dir: 1 } : null) : { key: c.key, dir: -1 },
                      )
                  : undefined
              }
              aria-sort={sort?.key === c.key ? (sort.dir === 1 ? "ascending" : "descending") : undefined}
            >
              {c.label}
              {sort?.key === c.key && <span className="ml-0.5">{sort.dir === 1 ? "↑" : "↓"}</span>}
            </th>
          ))}
          <th className="pr-3.5 text-right font-medium">{trailingLabel}</th>
        </tr>
      </thead>
      <tbody>
        {sorted.map((item) => (
          <Row
            key={item.instrument.instrument_key}
            item={item}
            showVolume={showVolume}
            showName={showName}
            marketOpen={marketOpen}
            trailing={trailing}
            spark={sparks[item.instrument.instrument_key]}
          />
        ))}
      </tbody>
    </table>
  );
}
