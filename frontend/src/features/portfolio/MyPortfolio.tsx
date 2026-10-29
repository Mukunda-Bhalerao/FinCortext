import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { cx, Skeleton } from "../../components/ui/primitives";
import { api } from "../../lib/api";
import { fmtAgo, fmtPrice } from "../../lib/format";
import type { PortfolioPlan, PortfolioSummary } from "../../lib/types";
import { pct, rupees } from "./format";

function Signed({ v, children }: { v: number | null | undefined; children: React.ReactNode }) {
  return (
    <span className={cx("num", v == null ? "text-faint" : v > 0 ? "text-up" : v < 0 ? "text-down" : "text-muted")}>
      {children}
    </span>
  );
}

/** Weight now against the plan's target, as two bars on one track. */
function Drift({ now, target }: { now: number; target: number | null }) {
  return (
    <div className="relative h-2 w-full rounded-full bg-surface-3" aria-hidden>
      <div
        className="absolute inset-y-0 left-0 rounded-full bg-accent/70"
        style={{ width: `${Math.min(100, now * 100)}%` }}
      />
      {target != null && (
        <div
          className="absolute -top-0.5 h-3 w-0.5 rounded bg-fg"
          style={{ left: `${Math.min(100, target * 100)}%` }}
          title={`Plan target ${pct(target, 0)}`}
        />
      )}
    </div>
  );
}

function BrokerLine({ s, onSync, syncing }: { s: PortfolioSummary; onSync: () => void; syncing: boolean }) {
  const b = s.broker;
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-2xs text-faint">
      <span
        className={cx(
          "h-1.5 w-1.5 rounded-full",
          b.can_sync ? "bg-up" : b.can_sync === false ? "bg-caution" : "bg-faint",
        )}
      />
      <span className="max-w-3xl">
        {b.can_sync && b.last_sync ? `Synced from Upstox ${fmtAgo(b.last_sync)}. ` : ""}
        {b.can_sync ? b.detail.replace(/^Synced .*?\.\s*/, "") : b.detail}
      </span>
      {b.connected && (
        <button
          onClick={onSync}
          disabled={syncing}
          className="font-medium text-accent hover:underline disabled:opacity-50"
        >
          {syncing ? "Syncing…" : "Sync from Upstox"}
        </button>
      )}
      <span>Read-only: FinCortext never places orders.</span>
    </div>
  );
}

/** The real portfolio: value, cost, P&L, today's move and drift from the chosen plan. */
export function MyPortfolio({ plan, onEdit }: { plan: PortfolioPlan | undefined; onEdit: () => void }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["summary"], queryFn: api.summary, refetchInterval: 60_000 });
  const [syncing, setSyncing] = useState(false);
  const sync = async () => {
    setSyncing(true);
    try {
      await api.syncHoldings();
      await Promise.all(["summary", "plan", "brief", "holdings"].map((k) => qc.invalidateQueries({ queryKey: [k] })));
    } finally {
      setSyncing(false);
    }
  };
  if (q.isPending) return <Skeleton className="h-24 rounded-lg" />;
  if (q.isError || !q.data) return null;
  const s = q.data;
  const target = new Map(plan?.trades?.lines.map((l) => [l.symbol, l.target_weight]) ?? []);
  if (s.holdings.length === 0) {
    return (
      <section className="flex flex-col gap-2 rounded-lg border border-dashed border-line-strong bg-surface p-4">
        <div className="flex flex-wrap items-center gap-3">
          <div>
            <h2 className="text-sm font-semibold text-fg">Add what you own</h2>
            <p className="text-xs text-muted">
              With your holdings, FinCortext tracks your real P&L, shows drift from your plan and turns suggestions into
              exact moves.
            </p>
          </div>
          <button onClick={onEdit} className="ml-auto rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-white">
            Enter holdings
          </button>
        </div>
        <BrokerLine s={s} onSync={() => void sync()} syncing={syncing} />
      </section>
    );
  }
  return (
    <section className="rounded-lg border border-line bg-surface">
      <div className="flex flex-wrap items-end gap-x-8 gap-y-3 border-b border-line p-4">
        <div>
          <div className="text-2xs tracking-wide text-faint uppercase">Your portfolio</div>
          <div className="num mt-0.5 text-2xl font-semibold text-fg">{rupees(s.total_value)}</div>
        </div>
        <div>
          <div className="text-2xs text-faint">Gain on cost</div>
          <div className="text-sm">
            <Signed v={s.pnl}>
              {s.pnl == null
                ? "Cost unknown"
                : `${s.pnl >= 0 ? "+" : "−"}${rupees(Math.abs(s.pnl))} (${pct(s.pnl_pct, 1, true)})`}
            </Signed>
          </div>
          {s.total_invested != null && (
            <div className="num text-2xs text-faint">Invested {rupees(s.total_invested)}</div>
          )}
        </div>
        <div>
          <div className="text-2xs text-faint">Today</div>
          <div className="text-sm">
            <Signed v={s.day_change}>
              {s.day_change == null ? "—" : `${s.day_change >= 0 ? "+" : "−"}${rupees(Math.abs(s.day_change))}`}
            </Signed>
          </div>
        </div>
        <button
          onClick={onEdit}
          className="ml-auto rounded-md border border-line px-2.5 py-1 text-xs text-muted hover:border-line-strong hover:text-fg"
        >
          Edit holdings
        </button>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-left text-sm">
          <thead>
            <tr className="border-b border-line text-2xs tracking-wide text-faint uppercase">
              <th className="px-4 py-1.5 font-medium">Stock</th>
              <th className="px-3 py-1.5 text-right font-medium">Value</th>
              <th className="px-3 py-1.5 text-right font-medium">Gain</th>
              <th className="px-3 py-1.5 text-right font-medium">Today</th>
              <th className="w-48 px-4 py-1.5 font-medium">Weight vs plan</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {s.holdings.map((h) => {
              const t = target.get(h.symbol) ?? null;
              const gap = t != null && h.weight != null ? h.weight - t : null;
              return (
                <tr key={h.instrument_key}>
                  <td className="px-4 py-2">
                    <Link
                      to={`/stock/${encodeURIComponent(h.symbol)}`}
                      className="font-medium text-fg hover:text-accent"
                    >
                      {h.symbol}
                    </Link>
                    <div className="num text-2xs text-faint">
                      {h.quantity.toLocaleString("en-IN")} × {fmtPrice(h.price)}
                      {h.avg_cost != null && ` · cost ${fmtPrice(h.avg_cost)}`}
                      {h.source === "upstox" && " · Upstox"}
                    </div>
                  </td>
                  <td className="num px-3 py-2 text-right text-fg">{rupees(h.value)}</td>
                  <td className="px-3 py-2 text-right">
                    <Signed v={h.pnl}>{h.pnl == null ? "—" : pct(h.pnl_pct, 1, true)}</Signed>
                  </td>
                  <td className="px-3 py-2 text-right">
                    <Signed v={h.day_change_pct}>{pct(h.day_change_pct, 2, true)}</Signed>
                  </td>
                  <td className="px-4 py-2">
                    <div className="num mb-1 flex justify-between text-2xs">
                      <span className="text-fg">{pct(h.weight, 0)}</span>
                      <span className={gap != null && Math.abs(gap) >= 0.05 ? "text-caution" : "text-faint"}>
                        {t == null ? "not in plan" : `target ${pct(t, 0)}`}
                      </span>
                    </div>
                    <Drift now={h.weight ?? 0} target={t} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="space-y-1 border-t border-line px-4 py-2.5">
        <BrokerLine s={s} onSync={() => void sync()} syncing={syncing} />
        {s.notes.map((n) => (
          <p key={n} className="text-2xs text-faint">
            {n}
          </p>
        ))}
      </div>
    </section>
  );
}
