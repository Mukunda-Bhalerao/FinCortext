import { useSparklines } from "../../lib/sparklines";
import { Sparkline } from "../../components/ui/visual";
import { toast } from "../../lib/toast";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { QuoteTable } from "../../components/QuoteTable";
import { IconClose, IconExternal } from "../../components/ui/icons";
import { cx, EmptyState, ErrorState, Panel, Segmented, Skeleton, SkeletonRows } from "../../components/ui/primitives";
import { api } from "../../lib/api";
import { fmtAgo, fmtPct, fmtStamp } from "../../lib/format";
import { mergeQuote, useLiveSubscription, useTick } from "../../lib/live";
import { useMarketOpen } from "../../lib/queries";
import type { LabeledQuote } from "../../lib/types";

export function WatchlistPanel({ limit, className }: { limit?: number; className?: string }) {
  const qc = useQueryClient();
  const marketOpen = useMarketOpen();
  const q = useQuery({
    queryKey: ["watchlist"],
    queryFn: api.watchlist,
    refetchInterval: marketOpen ? 30_000 : 300_000,
  });
  const remove = async (key: string) => {
    await api.unwatch(key);
    await qc.invalidateQueries({ queryKey: ["watchlist"] });
    toast("Removed from your watchlist", { tone: "info" });
  };
  const items = q.data ?? [];
  return (
    <Panel
      title="Watchlist"
      meta={items.length ? `${items.length} instruments` : undefined}
      className={className}
      actions={
        limit && items.length > limit ? (
          <Link to="/watchlist" className="text-2xs text-accent hover:underline">
            View all
          </Link>
        ) : undefined
      }
    >
      {q.isPending ? (
        <SkeletonRows />
      ) : q.isError ? (
        <ErrorState error={q.error} />
      ) : items.length === 0 ? (
        <EmptyState title="Your watchlist is empty">
          Search for a stock and use the star on its page to track it here.
        </EmptyState>
      ) : (
        <QuoteTable
          items={limit ? items.slice(0, limit) : items}
          sortable
          trailingLabel=""
          trailing={(item) => (
            <button
              onClick={(e) => {
                e.stopPropagation();
                void remove(item.instrument.instrument_key);
              }}
              className="invisible rounded p-0.5 text-faint group-hover:visible hover:text-fg"
              aria-label={`Remove ${item.label} from watchlist`}
            >
              <IconClose width={14} height={14} />
            </button>
          )}
        />
      )}
    </Panel>
  );
}

type MoverTab = "gainers" | "losers" | "most_active";

export function MoversPanel({ className, count = 8 }: { className?: string; count?: number }) {
  const [tab, setTab] = useState<MoverTab>("gainers");
  const marketOpen = useMarketOpen();
  const q = useQuery({
    queryKey: ["movers"],
    queryFn: api.movers,
    refetchInterval: marketOpen ? 30_000 : 300_000,
  });
  const d = q.data;
  const total = d ? d.advances + d.declines + d.unchanged : 0;
  return (
    <Panel
      title="Movers"
      meta={d ? `${d.universe} constituents` : undefined}
      className={className}
      actions={
        <Segmented
          value={tab}
          onChange={setTab}
          size="xs"
          options={[
            { value: "gainers", label: "Gainers" },
            { value: "losers", label: "Losers" },
            { value: "most_active", label: "Active" },
          ]}
        />
      }
    >
      {q.isPending ? (
        <SkeletonRows rows={8} />
      ) : q.isError ? (
        <ErrorState error={q.error} />
      ) : d && d.quotes_received === 0 ? (
        <EmptyState title="No quotes received for the constituents">
          {d.constituents_total === 0 ? "The NIFTY 50 constituent list could not be loaded from NSE." : undefined}
        </EmptyState>
      ) : d ? (
        <>
          {total > 0 && (
            <div className="border-b border-line px-3.5 py-2">
              <div className="flex justify-between text-2xs text-muted">
                <span className="text-up">{d.advances} advancing</span>
                {d.unchanged > 0 && <span>{d.unchanged} unchanged</span>}
                <span className="text-down">{d.declines} declining</span>
              </div>
              <div className="mt-1 flex h-1 overflow-hidden rounded-full bg-surface-3">
                <div className="bg-up" style={{ width: `${(d.advances / total) * 100}%` }} />
                <div className="ml-auto bg-down" style={{ width: `${(d.declines / total) * 100}%` }} />
              </div>
            </div>
          )}
          {d[tab].length === 0 ? (
            <EmptyState
              title={
                tab === "gainers"
                  ? "No advancing constituents"
                  : tab === "losers"
                    ? "No declining constituents"
                    : "No volume reported"
              }
            />
          ) : (
            <QuoteTable items={d[tab].slice(0, count)} showVolume={tab === "most_active"} showName={false} />
          )}
          <div className="border-t border-line px-3.5 py-1.5 text-2xs text-faint">
            {tab === "most_active" ? "Ranked by traded value. " : "Ranked by % change. "}
            {d.quotes_received}/{d.constituents_total} quoted · as of {fmtStamp(d.as_of)}
          </div>
        </>
      ) : null}
    </Panel>
  );
}

function SectorTile({ item, marketOpen, spark }: { item: LabeledQuote; marketOpen: boolean; spark?: number[] }) {
  const navigate = useNavigate();
  const tick = useTick(item.instrument.instrument_key);
  const q = mergeQuote(item.quote, tick, marketOpen);
  const pct = q.changePct;
  // Tint strength scales with magnitude, capped at 3%.
  const strength = pct == null ? 0 : Math.min(Math.abs(pct) / 3, 1);
  return (
    <button
      onClick={() => navigate(`/?chart=${encodeURIComponent(item.instrument.instrument_key)}`)}
      className="fc-card relative overflow-hidden rounded-lg border border-line px-2.5 py-2 text-left hover:border-line-strong"
      title={`${item.instrument.name ?? item.label} · ${q.observedAt ? fmtStamp(q.observedAt) : "no data"}`}
    >
      <span
        className={cx("absolute inset-0", pct == null ? "" : pct >= 0 ? "bg-up" : "bg-down")}
        style={{ opacity: 0.05 + strength * 0.3 }}
        aria-hidden
      />
      <span className="relative flex items-center justify-between gap-1">
        <span className="truncate text-xs text-fg">{item.label}</span>
        <Sparkline points={spark} width={40} height={14} fill={false} />
      </span>
      <span
        className={cx(
          "num relative mt-0.5 block text-sm font-medium",
          pct == null ? "text-faint" : pct > 0 ? "text-up" : pct < 0 ? "text-down" : "text-muted",
        )}
      >
        {fmtPct(pct)}
      </span>
    </button>
  );
}

export function SectorBoard({ className }: { className?: string }) {
  const marketOpen = useMarketOpen();
  const q = useQuery({
    queryKey: ["sectors"],
    queryFn: api.sectors,
    refetchInterval: marketOpen ? 60_000 : 300_000,
  });
  useLiveSubscription((q.data ?? []).map((i) => i.instrument.instrument_key));
  const items = (q.data ?? []).slice().sort((a, b) => (b.quote?.change_pct ?? -99) - (a.quote?.change_pct ?? -99));
  const sparks = useSparklines(items.map((i) => i.instrument.instrument_key));
  return (
    <Panel title="Sectors" meta="NSE sectoral indices" className={className}>
      {q.isPending ? (
        <div className="grid grid-cols-2 gap-1.5 p-3 sm:grid-cols-3 lg:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 12 }, (_, i) => (
            <Skeleton key={i} className="h-12" />
          ))}
        </div>
      ) : q.isError ? (
        <ErrorState error={q.error} />
      ) : items.length === 0 ? (
        <EmptyState title="Sector indices unavailable" />
      ) : (
        <div className="fc-stagger grid grid-cols-2 gap-1.5 p-3 sm:grid-cols-3 lg:grid-cols-2 xl:grid-cols-3">
          {items.map((i) => (
            <SectorTile
              key={i.instrument.instrument_key}
              item={i}
              marketOpen={marketOpen}
              spark={sparks[i.instrument.instrument_key]}
            />
          ))}
        </div>
      )}
    </Panel>
  );
}

export function NewsPanel({ className, limit = 14 }: { className?: string; limit?: number }) {
  const q = useQuery({ queryKey: ["news"], queryFn: api.news, refetchInterval: 600_000 });
  return (
    <Panel
      title="Market news"
      meta={q.data?.sources_ok.length ? q.data.sources_ok.join(", ") : undefined}
      className={className}
    >
      {q.isPending ? (
        <SkeletonRows rows={8} />
      ) : q.isError ? (
        <ErrorState error={q.error} />
      ) : q.data.items.length === 0 ? (
        <EmptyState title="No headlines available">
          {q.data.sources_failed.length
            ? `Could not reach: ${q.data.sources_failed.join(", ")}.`
            : "News feeds are turned off."}
        </EmptyState>
      ) : (
        <>
          <ul className="divide-y divide-line/60">
            {q.data.items.slice(0, limit).map((n) => (
              <li key={n.link}>
                <a
                  href={n.link}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="group block px-3.5 py-2 hover:bg-surface-2"
                >
                  <p className="line-clamp-2 text-sm leading-snug text-fg group-hover:text-accent">{n.title}</p>
                  <p className="mt-0.5 flex items-center gap-1.5 text-2xs text-faint">
                    <span className="text-muted">{n.publisher}</span>
                    <span>·</span>
                    <span title={fmtStamp(n.published_at)}>
                      {n.published_at ? fmtAgo(n.published_at) : "time not given"}
                    </span>
                    <IconExternal width={11} height={11} className="ml-auto opacity-0 group-hover:opacity-100" />
                  </p>
                </a>
              </li>
            ))}
          </ul>
          <div className="border-t border-line px-3.5 py-1.5 text-2xs text-faint">
            Headlines link to the original publisher. Fetched {fmtStamp(q.data.fetched_at)}
            {q.data.sources_failed.length > 0 && ` · unavailable: ${q.data.sources_failed.join(", ")}`}
          </div>
        </>
      )}
    </Panel>
  );
}
