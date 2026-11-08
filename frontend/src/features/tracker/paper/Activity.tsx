import { Ring, StockAvatar } from "../../../components/ui/visual";
import { toast } from "../../../lib/toast";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Term } from "../../../components/Term";
import { EmptyState, cx } from "../../../components/ui/primitives";
import { api } from "../../../lib/api";
import { fmtDateTimeIST, fmtPrice } from "../../../lib/format";
import type { AccountActivity, ClosedTrade, JournalEntry, PaperOrder } from "../../../lib/types";
import { pct, rupees } from "../../portfolio/format";
import { Signed } from "../PortfoliosPage";
import { fmtDay, inr } from "../StockStory";

const STATUS: Record<PaperOrder["status"], string> = {
  OPEN: "text-accent",
  FILLED: "text-up",
  CANCELLED: "text-faint",
  EXPIRED: "text-faint",
  REJECTED: "text-down",
};

function describeOrder(o: PaperOrder): string {
  if (o.kind === "LIMIT") return `Limit ${fmtPrice(o.limit_price)}`;
  if (o.kind === "SL") return `Stop ${fmtPrice(o.trigger_price)}`;
  return "Market";
}

export function OrdersList({ pid, orders }: { pid: string; orders: PaperOrder[] }) {
  const qc = useQueryClient();
  const cancel = useMutation({
    mutationFn: (oid: string) => api.cancelOrder(pid, oid),
    onSuccess: (o) => {
      toast(`Cancelled your ${o.side === "BUY" ? "buy" : "sell"} order for ${o.symbol}`, {
        tone: "info",
        body: o.side === "BUY" ? "The cash it was holding is free again." : undefined,
      });
      void qc.invalidateQueries({ queryKey: ["activity", pid] });
      void qc.invalidateQueries({ queryKey: ["tracked", pid] });
    },
  });
  if (!orders.length)
    return <EmptyState title="No orders yet">Place your first order with the Trade button.</EmptyState>;
  const open = orders.filter((o) => o.status === "OPEN");
  const done = orders.filter((o) => o.status !== "OPEN");
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[760px] text-sm">
        <thead>
          <tr className="text-2xs tracking-wide text-faint uppercase">
            <th className="px-3 py-2 text-left font-medium">Placed</th>
            <th className="px-3 py-2 text-left font-medium">Order</th>
            <th className="px-3 py-2 text-right font-medium">Shares</th>
            <th className="px-3 py-2 text-left font-medium">Type</th>
            <th className="px-3 py-2 text-left font-medium">Status</th>
            <th className="px-3 py-2 text-right font-medium">Fill</th>
            <th className="px-3 py-2 text-right font-medium">Charges</th>
            <th className="px-3 py-2" />
          </tr>
        </thead>
        <tbody>
          {[...open, ...done].map((o) => (
            <tr key={o.id} className="border-t border-line align-top">
              <td className="px-3 py-2 text-xs whitespace-nowrap text-muted">{fmtDateTimeIST(o.created_at)}</td>
              <td className="px-3 py-2">
                <span className={cx("font-medium", o.side === "BUY" ? "text-up" : "text-down")}>
                  {o.side === "BUY" ? "Buy" : "Sell"}
                </span>{" "}
                <span className="text-fg">{o.symbol}</span>
                {o.source.startsWith("strategy:") && (
                  <span className="ml-1.5 rounded bg-surface-3 px-1 text-2xs text-muted">strategy</span>
                )}
                {o.reason && <div className="max-w-72 truncate text-2xs text-faint">{o.reason}</div>}
                {o.message && <div className="max-w-72 text-2xs text-caution">{inr(o.message)}</div>}
              </td>
              <td className="num px-3 py-2 text-right">{o.quantity}</td>
              <td className="px-3 py-2 text-xs text-muted">
                {describeOrder(o)}
                {o.validity === "GTC" && o.kind !== "MARKET" && <span className="text-faint"> · until cancelled</span>}
              </td>
              <td className={cx("px-3 py-2 text-xs font-medium", STATUS[o.status])}>
                {o.status === "OPEN" ? "Open" : o.status.charAt(0) + o.status.slice(1).toLowerCase()}
              </td>
              <td className="num px-3 py-2 text-right" title={o.fill_basis ?? undefined}>
                {o.fill_price != null ? fmtPrice(o.fill_price) : "—"}
              </td>
              <td className="num px-3 py-2 text-right text-muted">
                {o.charges ? `₹${o.charges.total.toFixed(2)}` : "—"}
              </td>
              <td className="px-3 py-2 text-right">
                {o.status === "OPEN" && (
                  <button
                    onClick={() => cancel.mutate(o.id)}
                    disabled={cancel.isPending}
                    className="text-2xs text-faint hover:text-down"
                  >
                    Cancel
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Outcome({ e }: { e: JournalEntry }) {
  return (
    <div className="text-right">
      <Signed v={e.outcome_pct} className="text-sm font-medium">
        {pct(e.outcome_pct, 1, true)}
      </Signed>
      <div className="text-2xs">
        <Signed v={e.outcome}>{e.outcome != null ? `${e.outcome > 0 ? "+" : ""}${rupees(e.outcome)}` : "—"}</Signed>
      </div>
    </div>
  );
}

export function Journal({ entries }: { entries: JournalEntry[] }) {
  if (!entries.length)
    return (
      <EmptyState title="Your journal is empty">
        Each buy you make appears here with the reason you wrote, and later with how it turned out against the market.
      </EmptyState>
    );
  return (
    <ul className="divide-y divide-line">
      {entries.map((e, k) => (
        <li key={k} className="flex gap-3 px-3.5 py-3 hover:bg-surface-2/60">
          <StockAvatar symbol={e.symbol} size={34} />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
              <span className="text-sm font-semibold text-fg">{e.symbol}</span>
              <span className="text-2xs text-faint">
                {e.quantity} at {fmtPrice(e.price)} · {fmtDay(e.at)}
              </span>
              <span
                className={cx(
                  "rounded px-1.5 py-0.5 text-2xs",
                  e.kind === "open" ? "bg-accent-soft text-accent" : "bg-surface-3 text-muted",
                )}
              >
                {e.kind === "open" ? "Holding" : "Closed"}
              </span>
              {e.tag && <span className="rounded-full border border-line px-1.5 text-2xs text-muted">{e.tag}</span>}
            </div>
            <p className={cx("mt-1 text-xs", e.reason ? "text-fg" : "text-faint italic")}>
              {e.reason ? `“${e.reason}”` : "No reason written"}
            </p>
            <p className="mt-0.5 text-2xs text-muted">{e.verdict}</p>
          </div>
          <Outcome e={e} />
        </li>
      ))}
    </ul>
  );
}

function Big({ label, children, sub }: { label: React.ReactNode; children: React.ReactNode; sub?: React.ReactNode }) {
  return (
    <div className="rounded-md border border-line bg-surface-2 p-3">
      <div className="text-2xs tracking-wide text-faint uppercase">{label}</div>
      <div className="num mt-0.5 text-lg font-semibold text-fg">{children}</div>
      {sub && <div className="text-2xs text-muted">{sub}</div>}
    </div>
  );
}

function TradeLine({ t, label }: { t: ClosedTrade; label: string }) {
  return (
    <div className="text-xs">
      <span className="text-faint">{label}: </span>
      <span className="text-fg">{t.symbol}</span> <Signed v={t.return_pct}>{pct(t.return_pct, 1, true)}</Signed>
      <span className="text-faint">
        {" "}
        ({rupees(t.net)}, {t.holding_days} days)
      </span>
    </div>
  );
}

export function ScorecardView({ a }: { a: AccountActivity }) {
  const s = a.scorecard;
  return (
    <div className="flex flex-col gap-4 p-3.5">
      {s.lessons.length > 0 && (
        <div className="rounded-md border border-accent/40 bg-accent-soft p-3">
          <h3 className="text-2xs font-semibold tracking-wide text-accent uppercase">What your record shows</h3>
          <ul className="mt-1.5 list-disc space-y-1 pl-4 text-sm text-fg">
            {s.lessons.map((l, k) => (
              <li key={k}>{inr(l)}</li>
            ))}
          </ul>
        </div>
      )}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Big label="Closed trades" sub={`${s.open_positions} still open`}>
          {s.closed_trades}
        </Big>
        <Big label={<Term k="win rate">Win rate</Term>} sub={`${s.wins} won, ${s.losses} lost`}>
          <span className="flex items-center gap-2.5">
            <Ring value={s.win_rate} size={34} stroke={4} tone={(s.win_rate ?? 0) >= 0.5 ? "up" : "caution"} />
            {pct(s.win_rate, 0)}
          </span>
        </Big>
        <Big label={<Term k="realised P&L">Realised</Term>} sub="net of all charges">
          <Signed v={s.realized_net}>{rupees(s.realized_net)}</Signed>
        </Big>
        <Big
          label={<Term k="benchmark">Beat the NIFTY 50</Term>}
          sub={
            s.index_equivalent != null
              ? `The index would have made ${rupees(s.index_equivalent)} on the same money`
              : "on the same dates"
          }
        >
          {s.compared ? (
            <span className="flex items-center gap-2.5">
              <Ring value={s.beat_index / s.compared} size={34} stroke={4} tone="accent" />
              {s.beat_index} of {s.compared}
            </span>
          ) : (
            "—"
          )}
        </Big>
        <Big label="Average win">
          <Signed v={s.average_win}>{pct(s.average_win, 1, true)}</Signed>
        </Big>
        <Big label="Average loss">
          <Signed v={s.average_loss}>{pct(s.average_loss, 1, true)}</Signed>
        </Big>
        <Big label={<Term k="profit factor">Profit factor</Term>}>
          {s.profit_factor != null ? s.profit_factor.toFixed(2) : "—"}
        </Big>
        <Big
          label="Charges paid"
          sub={s.charges_share_of_gross != null ? `${pct(s.charges_share_of_gross, 0)} of gross profit` : undefined}
        >
          ₹{s.charges_paid.toFixed(0)}
        </Big>
      </div>
      {(s.days_held_winners != null || s.days_held_losers != null) && (
        <p className="text-xs text-muted">
          Average days held: winners {s.days_held_winners?.toFixed(0) ?? "—"}, losers{" "}
          {s.days_held_losers?.toFixed(0) ?? "—"}.
        </p>
      )}
      {(s.best || s.worst) && (
        <div className="flex flex-col gap-1">
          {s.best && <TradeLine t={s.best} label="Best trade" />}
          {s.worst && s.worst.id !== s.best?.id && <TradeLine t={s.worst} label="Worst trade" />}
        </div>
      )}
      {s.by_tag.length > 0 && (
        <div>
          <h3 className="mb-1.5 text-2xs font-semibold tracking-wide text-faint uppercase">By reason tag</h3>
          <table className="w-full max-w-xl text-xs">
            <thead>
              <tr className="text-2xs text-faint">
                <th className="px-2 py-1 text-left font-medium">Tag</th>
                <th className="px-2 py-1 text-right font-medium">Trades</th>
                <th className="px-2 py-1 text-right font-medium">Won</th>
                <th className="px-2 py-1 text-right font-medium">Average</th>
                <th className="px-2 py-1 text-right font-medium">Net</th>
              </tr>
            </thead>
            <tbody>
              {s.by_tag.map((t) => (
                <tr key={t.tag} className="border-t border-line">
                  <td className="px-2 py-1.5 text-fg">{t.tag}</td>
                  <td className="num px-2 py-1.5 text-right">{t.trades}</td>
                  <td className="num px-2 py-1.5 text-right">{t.wins}</td>
                  <td className="px-2 py-1.5 text-right">
                    <Signed v={t.average_return}>{pct(t.average_return, 1, true)}</Signed>
                  </td>
                  <td className="px-2 py-1.5 text-right">
                    <Signed v={t.net}>{rupees(t.net)}</Signed>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {s.tax.length > 0 && (
        <div>
          <h3 className="mb-1.5 text-2xs font-semibold tracking-wide text-faint uppercase">Estimated tax</h3>
          <table className="w-full max-w-xl text-xs">
            <thead>
              <tr className="text-2xs text-faint">
                <th className="px-2 py-1 text-left font-medium">Year</th>
                <th className="px-2 py-1 text-right font-medium">
                  <Term k="STCG">Short-term</Term>
                </th>
                <th className="px-2 py-1 text-right font-medium">
                  <Term k="LTCG">Long-term</Term>
                </th>
                <th className="px-2 py-1 text-right font-medium">Tax</th>
              </tr>
            </thead>
            <tbody>
              {s.tax.map((t) => (
                <tr key={t.year} className="border-t border-line">
                  <td className="px-2 py-1.5 text-fg">{t.year}</td>
                  <td className="px-2 py-1.5 text-right">
                    <Signed v={t.short_term_gain}>{rupees(t.short_term_gain)}</Signed>
                  </td>
                  <td className="px-2 py-1.5 text-right">
                    <Signed v={t.long_term_gain}>{rupees(t.long_term_gain)}</Signed>
                  </td>
                  <td className="num px-2 py-1.5 text-right text-fg">{rupees(t.estimated_tax)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-1 text-2xs text-faint">{inr(s.tax[0]?.note ?? "")}</p>
        </div>
      )}
    </div>
  );
}
