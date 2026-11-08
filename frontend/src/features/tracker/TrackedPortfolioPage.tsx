import { useSparklines } from "../../lib/sparklines";
import { AnimatedNumber, Sparkline, StockAvatar } from "../../components/ui/visual";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { EquityChart, type EquityLine } from "../../components/charts/EquityChart";
import { useFlash } from "../../components/QuoteTable";
import { EmptyState, ErrorState, Panel, Segmented, Skeleton, SkeletonRows, cx } from "../../components/ui/primitives";
import { api } from "../../lib/api";
import { fmtAgo, fmtPrice, fmtStamp } from "../../lib/format";
import { useLiveSubscription, useTick } from "../../lib/live";
import { useMarketOpen } from "../../lib/queries";
import { toast } from "../../lib/toast";
import { Term } from "../../components/Term";
import type { OrderSide, PortfolioReview, ReviewPeriod, TrackedPortfolio, TrackedPosition } from "../../lib/types";
import { pct, rupees } from "../portfolio/format";
import { AddStock } from "./AddStock";
import { Signed } from "./PortfoliosPage";
import { Journal, OrdersList, ScorecardView } from "./paper/Activity";
import { OrderTicket } from "./paper/OrderTicket";
import { inr, StockStory } from "./StockStory";

const PERIODS: { value: ReviewPeriod; label: string }[] = [
  { value: "last_visit", label: "Since last visit" },
  { value: "today", label: "Today" },
  { value: "1w", label: "1W" },
  { value: "1m", label: "1M" },
  { value: "start", label: "Since start" },
];

const pendingLeave = new Map<string, ReturnType<typeof setTimeout>>();

/** Remember the visit when the page is left, so the next "since your last visit" starts here.
 * The mark is deferred a moment so a remount (dev double-mount, quick back-and-forth) cancels it. */
function useMarkViewedOnLeave(id: string | undefined) {
  useEffect(() => {
    if (!id) return;
    clearTimeout(pendingLeave.get(id));
    pendingLeave.delete(id);
    const url = `/api/tracker/${encodeURIComponent(id)}/viewed`;
    const onHide = () => navigator.sendBeacon?.(url);
    window.addEventListener("pagehide", onHide);
    return () => {
      window.removeEventListener("pagehide", onHide);
      pendingLeave.set(
        id,
        setTimeout(() => {
          pendingLeave.delete(id);
          void api.markViewed(id).catch(() => undefined);
        }, 1000),
      );
    };
  }, [id]);
}

function Header({ p }: { p: TrackedPortfolio }) {
  const marketOpen = useMarketOpen();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(p.name);
  const rename = useMutation({
    mutationFn: (n: string) => api.renameTracked(p.id, n),
    onSuccess: (np) => {
      qc.setQueryData(["tracked", p.id], np);
      void qc.invalidateQueries({ queryKey: ["tracked"], exact: true });
      setEditing(false);
    },
  });
  const remove = useMutation({
    mutationFn: () => api.deleteTracked(p.id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["tracked"], exact: true });
      navigate("/portfolios");
    },
  });
  return (
    <div className="flex flex-wrap items-end gap-x-6 gap-y-3">
      <div className="min-w-0">
        <Link to="/portfolios" className="text-2xs text-faint hover:text-fg">
          ← Portfolios
        </Link>
        {editing ? (
          <form
            className="mt-0.5 flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (name.trim()) rename.mutate(name.trim());
            }}
          >
            <input
              autoFocus
              value={name}
              maxLength={60}
              onChange={(e) => setName(e.target.value)}
              aria-label="Portfolio name"
              className="h-8 rounded-md border border-line bg-surface-2 px-2.5 text-sm text-fg focus:border-accent focus:outline-none"
            />
            <button type="submit" className="text-xs text-accent">
              Save
            </button>
            <button type="button" onClick={() => setEditing(false)} className="text-xs text-muted">
              Cancel
            </button>
          </form>
        ) : (
          <h1 className="flex items-baseline gap-2 text-lg font-semibold text-fg">
            <span className="truncate">{p.name}</span>
            <button onClick={() => setEditing(true)} className="text-2xs font-normal text-faint hover:text-fg">
              Rename
            </button>
            <button
              onClick={() => {
                if (window.confirm(`Delete "${p.name}" and its ${p.positions.length} stocks? This cannot be undone.`))
                  remove.mutate();
              }}
              className="text-2xs font-normal text-faint hover:text-down"
            >
              Delete
            </button>
          </h1>
        )}
      </div>
      {p.kind === "paper" && (
        <div className="ml-auto flex flex-wrap gap-x-6 gap-y-2">
          <div>
            <div className="text-2xs tracking-wide text-faint uppercase">Account value</div>
            <div className="num text-2xl font-semibold tracking-tight text-fg">
              <AnimatedNumber value={p.account_value} format={(v) => rupees(v)} />
            </div>
          </div>
          <div>
            <div className="text-2xs tracking-wide text-faint uppercase">Return</div>
            <Signed v={p.account_return} className="text-lg">
              {pct(p.account_return, 2, true)}
            </Signed>
            <div className="text-2xs text-faint">on {rupees(p.starting_cash)} start</div>
          </div>
          <div>
            <div className="text-2xs tracking-wide text-faint uppercase">Free cash</div>
            <div className="num text-lg text-fg">{rupees((p.cash ?? 0) - p.reserved)}</div>
            {p.reserved > 0 && <div className="text-2xs text-faint">{rupees(p.reserved)} held for open orders</div>}
          </div>
          <div>
            <div className="text-2xs tracking-wide text-faint uppercase">
              <Term k="realised P&L">Realised</Term>
            </div>
            <Signed v={p.realized} className="text-lg">
              {rupees(p.realized)}
            </Signed>
          </div>
          <div>
            <div className="text-2xs tracking-wide text-faint uppercase">Charges paid</div>
            <div className="num text-lg text-muted">₹{p.charges_paid.toFixed(0)}</div>
          </div>
        </div>
      )}
      {p.kind !== "paper" && p.positions.length > 0 && (
        <div className="ml-auto flex flex-wrap gap-x-6 gap-y-2">
          <div>
            <div className="text-2xs tracking-wide text-faint uppercase">Value</div>
            <div className="num text-lg font-semibold text-fg">{rupees(p.value)}</div>
          </div>
          <div>
            <div className="text-2xs tracking-wide text-faint uppercase">Invested</div>
            <div className="num text-lg text-muted">{rupees(p.cost)}</div>
          </div>
          <div>
            <div className="text-2xs tracking-wide text-faint uppercase">Overall gain</div>
            <Signed v={p.pnl} className="text-lg">
              {p.pnl != null && p.pnl > 0 ? "+" : ""}
              {rupees(p.pnl)} <span className="text-sm">({pct(p.pnl_pct, 1, true)})</span>
            </Signed>
          </div>
          <div>
            <div className="text-2xs tracking-wide text-faint uppercase">{marketOpen ? "Today" : "Last session"}</div>
            <Signed v={p.day_change} className="text-lg">
              {p.day_change != null && p.day_change > 0 ? "+" : ""}
              {rupees(p.day_change)} <span className="text-sm">({pct(p.day_change_pct, 2, true)})</span>
            </Signed>
          </div>
        </div>
      )}
    </div>
  );
}

/** How much of the change the market alone explains, and how much the stock choices added. */
function MarketSplit({ r }: { r: PortfolioReview }) {
  if (r.market_part == null || r.selection_part == null) return null;
  if (r.change === 0 && r.market_part === 0) return null;
  return (
    <div className="grid grid-cols-3 gap-3 border-t border-line pt-3">
      <div>
        <div className="text-2xs text-faint">Change</div>
        <Signed v={r.change} className="text-sm font-medium">
          {r.change > 0 ? "+" : ""}
          {rupees(r.change)} ({pct(r.change_pct, 2, true)})
        </Signed>
      </div>
      <div title={`What the portfolio would have moved if it had tracked the ${r.benchmark_label} exactly`}>
        <div className="text-2xs text-faint">
          From the market ({r.benchmark_label} {pct(r.benchmark_return, 2, true)})
        </div>
        <Signed v={r.market_part} className="text-sm">
          {r.market_part > 0 ? "+" : ""}
          {rupees(r.market_part)}
        </Signed>
      </div>
      <div title="The rest: what your particular stocks did beyond the market">
        <div className="text-2xs text-faint">From your stock picks</div>
        <Signed v={r.selection_part} className="text-sm">
          {r.selection_part > 0 ? "+" : ""}
          {rupees(r.selection_part)}
        </Signed>
      </div>
    </div>
  );
}

function ReviewSection({
  id,
  period,
  setPeriod,
}: {
  id: string;
  period: ReviewPeriod;
  setPeriod: (p: ReviewPeriod) => void;
}) {
  // The review is a snapshot of one visit: it is not refetched in the background.
  // Dropped once the page closes, so the next visit computes afresh.
  const base = { staleTime: Infinity, gcTime: 0, refetchOnWindowFocus: false, retry: 1 } as const;
  const review = useQuery({
    queryKey: ["tracked-review", id, period, false],
    queryFn: () => api.review(id, period, false),
    ...base,
  });
  const narrated = useQuery({
    queryKey: ["tracked-review", id, period, true],
    queryFn: () => api.review(id, period, true),
    enabled: review.isSuccess && review.data.stocks.length > 0,
    ...base,
  });
  const r = review.data;
  const narrative = narrated.data?.narrative ?? null;

  const lines = useMemo<EquityLine[]>(
    () =>
      r && r.value_series.length > 1
        ? [
            { label: "Value", points: r.value_series, tone: "accent" },
            { label: "Invested", points: r.cost_series, tone: "muted", dashed: true },
          ]
        : [],
    [r],
  );
  const stocks = useMemo(
    () => (r ? [...r.stocks].sort((a, b) => Math.abs(b.contribution) - Math.abs(a.contribution)) : []),
    [r],
  );

  return (
    <section className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-semibold tracking-tight text-fg">What happened</h2>
        <div className="ml-auto overflow-x-auto">
          <Segmented value={period} onChange={setPeriod} options={PERIODS} />
        </div>
      </div>
      {review.isPending ? (
        <div className="rounded-lg border border-line bg-surface p-4">
          <Skeleton className="h-5 w-2/3" />
          <Skeleton className="mt-3 h-3 w-full" />
          <Skeleton className="mt-2 h-3 w-5/6" />
        </div>
      ) : review.isError ? (
        <Panel>
          <ErrorState error={review.error} />
        </Panel>
      ) : (
        r && (
          <>
            <div className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-2xs text-faint">
                <span className="font-medium tracking-wide text-accent uppercase">{r.period_label}</span>
                <span>{r.start_basis}</span>
                <span>· as of {fmtStamp(r.end)}</span>
              </div>
              <p className="text-base leading-snug font-semibold text-fg sm:text-lg">{inr(r.headline)}</p>
              {narrative ? (
                <div>
                  <p className="max-w-4xl text-sm leading-relaxed text-muted">{narrative.text}</p>
                  <p
                    className="mt-1 text-2xs text-faint"
                    title="Written by a language model from the facts on this page; numbers not found in those facts are rejected"
                  >
                    Summary written by {narrative.model} from {narrative.cited.length} checked facts
                  </p>
                </div>
              ) : (
                narrated.isFetching && <p className="text-2xs text-faint">Writing a plain-language summary…</p>
              )}
              {r.points.length > 0 && (
                <ul className="list-disc space-y-1 pl-4 text-sm text-muted">
                  {r.points.map((pt, i) => (
                    <li key={i}>{inr(pt)}</li>
                  ))}
                </ul>
              )}
              <MarketSplit r={r} />
              {r.change === 0 && r.period !== "1w" && r.period !== "1m" && (
                <button onClick={() => setPeriod("1w")} className="self-start text-xs text-accent hover:underline">
                  See the past week instead
                </button>
              )}
              {r.gaps.length > 0 && (
                <ul className="space-y-0.5 text-2xs text-caution">
                  {r.gaps.map((g, i) => (
                    <li key={i}>{g}</li>
                  ))}
                </ul>
              )}
            </div>
            {stocks.length > 0 && (
              <div className="flex flex-col gap-2">
                <h3 className="text-2xs font-semibold tracking-wide text-faint uppercase">
                  Stock by stock, biggest effect first
                </h3>
                {stocks.map((s, i) => (
                  <StockStory key={`${s.symbol}-${i}`} s={s} defaultOpen={i === 0} />
                ))}
              </div>
            )}
            {lines.length > 0 && (
              <Panel title="Value over time" meta="Daily closes, with today's live value as the last point">
                <div className="p-2">
                  <EquityChart lines={lines} unit="rupees" height={240} />
                </div>
              </Panel>
            )}
          </>
        )
      )}
    </section>
  );
}

function PositionRow({
  pid,
  p,
  onSell,
  spark,
}: {
  pid: string;
  p: TrackedPosition;
  onSell?: (p: TrackedPosition) => void;
  spark?: number[];
}) {
  const qc = useQueryClient();
  const tick = useTick(p.instrument_key);
  const marketOpen = useMarketOpen();
  const [editing, setEditing] = useState(false);
  const [qty, setQty] = useState(String(p.quantity));
  const price = marketOpen && tick?.ltp != null ? tick.ltp : p.price;
  const flash = useFlash(price);
  const value = price != null ? price * p.quantity : null;
  const pnl = value != null ? value - p.cost : null;
  const dayPct = marketOpen && tick?.change_pct != null ? tick.change_pct / 100 : p.day_change_pct;
  const onDone = (np: TrackedPortfolio) => {
    qc.setQueryData(["tracked", pid], np);
    void qc.invalidateQueries({ queryKey: ["tracked-review", pid] });
    void qc.invalidateQueries({ queryKey: ["tracked"], exact: true });
  };
  const save = useMutation({
    mutationFn: (n: number) => api.setPositionQuantity(pid, p.id, n),
    onSuccess: (np) => {
      onDone(np);
      setEditing(false);
    },
  });
  const remove = useMutation({ mutationFn: () => api.removePosition(pid, p.id), onSuccess: onDone });
  return (
    <tr className="border-t border-line">
      <td className="px-3 py-2">
        <div className="flex items-center gap-2.5">
          <StockAvatar symbol={p.symbol} size={30} />
          <div className="min-w-0">
            <Link to={`/stock/${encodeURIComponent(p.symbol)}`} className="font-medium text-fg hover:text-accent">
              {p.symbol}
            </Link>
            <div className="max-w-48 truncate text-2xs text-faint">{p.sector}</div>
          </div>
        </div>
      </td>
      <td className="num px-3 py-2 text-right">
        {editing ? (
          <form
            className="flex justify-end gap-1"
            onSubmit={(e) => {
              e.preventDefault();
              if (Number(qty) > 0) save.mutate(Number(qty));
            }}
          >
            <input
              autoFocus
              type="number"
              min={1}
              step="any"
              value={qty}
              onChange={(e) => setQty(e.target.value)}
              aria-label={`Shares of ${p.symbol}`}
              className="h-6 w-20 rounded border border-line bg-surface-2 px-1.5 text-right text-xs"
            />
            <button type="submit" className="text-2xs text-accent">
              Save
            </button>
          </form>
        ) : (
          p.quantity
        )}
      </td>
      <td
        className="num px-3 py-2 text-right"
        title={[p.entry_basis, p.reason && `Why: ${p.reason}`].filter(Boolean).join("\n")}
      >
        {fmtPrice(p.entry_price)}
        <div className="text-2xs text-faint">{fmtAgo(p.entry_at)}</div>
        {p.break_even != null && <div className="text-2xs text-faint">break-even {fmtPrice(p.break_even)}</div>}
      </td>
      <td className={cx("num rounded px-3 py-2 text-right", flash)} title={p.price_basis ?? undefined}>
        <div className="flex items-center justify-end gap-2">
          <Sparkline points={spark} width={52} height={18} className="hidden md:block" />
          {fmtPrice(price)}
        </div>
      </td>
      <td className="num px-3 py-2 text-right">{rupees(value)}</td>
      <td className="px-3 py-2 text-right">
        <Signed v={pnl}>{pct(pnl != null && p.cost ? pnl / p.cost : null, 1, true)}</Signed>
        <div className="text-2xs">
          <Signed v={pnl}>{rupees(pnl)}</Signed>
        </div>
      </td>
      <td className="px-3 py-2 text-right">
        <Signed v={dayPct}>{pct(dayPct, 2, true)}</Signed>
      </td>
      <td className="px-3 py-2 text-right whitespace-nowrap">
        {onSell ? (
          <button
            onClick={() => onSell(p)}
            className="rounded border border-down/50 px-2 py-0.5 text-2xs font-medium text-down hover:bg-down/10"
          >
            Sell
          </button>
        ) : (
          <>
            <button onClick={() => setEditing((v) => !v)} className="text-2xs text-faint hover:text-fg">
              {editing ? "Cancel" : "Edit"}
            </button>
            <button
              onClick={() => {
                if (window.confirm(`Remove ${p.symbol} from this portfolio?`)) remove.mutate();
              }}
              className="ml-2 text-2xs text-faint hover:text-down"
            >
              Remove
            </button>
          </>
        )}
      </td>
    </tr>
  );
}

function Positions({ p, onSell }: { p: TrackedPortfolio; onSell?: (p: TrackedPosition) => void }) {
  const marketOpen = useMarketOpen();
  useLiveSubscription(p.positions.map((x) => x.instrument_key));
  const sparks = useSparklines(p.positions.map((x) => x.instrument_key));
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px] text-sm">
        <thead>
          <tr className="text-2xs tracking-wide text-faint uppercase">
            <th className="px-3 py-2 text-left font-medium">Stock</th>
            <th className="px-3 py-2 text-right font-medium">Shares</th>
            <th className="px-3 py-2 text-right font-medium">Bought at</th>
            <th className="px-3 py-2 text-right font-medium">Price</th>
            <th className="px-3 py-2 text-right font-medium">Value</th>
            <th className="px-3 py-2 text-right font-medium">Gain</th>
            <th className="px-3 py-2 text-right font-medium">{marketOpen ? "Today" : "Last session"}</th>
            <th className="px-3 py-2" />
          </tr>
        </thead>
        <tbody>
          {p.positions.map((x) => (
            <PositionRow key={x.id} pid={p.id} p={x} onSell={onSell} spark={sparks[x.instrument_key]} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

type Tab = "overview" | "orders" | "journal" | "scorecard";
type Ticket = { symbol?: string; side?: OrderSide; quantity?: number; key: number };

function PaperAccount({
  p,
  period,
  setPeriod,
}: {
  p: TrackedPortfolio;
  period: ReviewPeriod;
  setPeriod: (v: ReviewPeriod) => void;
}) {
  const [tab, setTab] = useState<Tab>("overview");
  const [ticket, setTicket] = useState<Ticket | null>(p.positions.length === 0 ? { key: 0 } : null);
  const activity = useQuery({
    queryKey: ["activity", p.id],
    queryFn: () => api.activity(p.id),
    refetchInterval: 15_000,
  });
  const openOrders = activity.data?.orders.filter((o) => o.status === "OPEN").length ?? 0;
  // Tell the user when something they were waiting for happens while they watch.
  const seen = useRef<Map<string, string> | null>(null);
  const qc = useQueryClient();
  useEffect(() => {
    const orders = activity.data?.orders;
    if (!orders) return;
    const before = seen.current;
    seen.current = new Map(orders.map((o) => [o.id, o.status]));
    if (!before) return;
    let changed = false;
    for (const o of orders) {
      if (before.get(o.id) !== "OPEN" || o.status === "OPEN") continue;
      changed = true;
      const verb = o.side === "BUY" ? "Bought" : "Sold";
      if (o.status === "FILLED")
        toast(`${verb} ${o.quantity} ${o.symbol} at ${fmtPrice(o.fill_price)}`, {
          body: o.parent_id
            ? o.kind === "SL"
              ? "Your stop-loss was hit."
              : "Your target was reached."
            : (o.fill_basis ?? undefined),
        });
      else if (o.status === "REJECTED")
        toast(`${o.symbol} order rejected`, { tone: "error", body: o.message ?? undefined });
      else if (o.status === "EXPIRED") toast(`${o.symbol} day order expired unfilled`, { tone: "warning" });
    }
    if (changed) void qc.invalidateQueries({ queryKey: ["tracked", p.id] });
  }, [activity.data, qc, p.id]);
  const tabs: { value: Tab; label: string }[] = [
    { value: "overview", label: "Overview" },
    { value: "orders", label: openOrders ? `Orders (${openOrders} open)` : "Orders" },
    { value: "journal", label: "Journal" },
    { value: "scorecard", label: "Scorecard" },
  ];
  const sell = (x: TrackedPosition) => {
    const sameStock = p.positions.filter((y) => y.symbol === x.symbol).reduce((n, y) => n + y.quantity, 0);
    setTicket({ symbol: x.symbol, side: "SELL", quantity: sameStock, key: Date.now() });
    window.scrollTo({ top: 0, behavior: "smooth" });
  };
  return (
    <>
      <Panel
        title="Trade"
        meta="Virtual money, live prices, real charges"
        actions={
          <button
            onClick={() => setTicket(ticket ? null : { key: Date.now() })}
            className={cx(
              "h-7 rounded-md px-3 text-xs font-medium",
              ticket ? "border border-line text-muted" : "bg-accent text-white",
            )}
          >
            {ticket ? "Close" : "New order"}
          </button>
        }
      >
        {ticket ? (
          <div className="p-3.5">
            <OrderTicket
              key={ticket.key}
              pid={p.id}
              initial={ticket}
              onDone={() => {
                setTicket(null);
                setTab("orders");
              }}
            />
          </div>
        ) : (
          <p className="px-3.5 py-2.5 text-xs text-muted">
            Buy with a written reason, an optional target and stop-loss, and see the exact charges before you place it.
          </p>
        )}
      </Panel>
      <div className="overflow-x-auto">
        <Segmented value={tab} onChange={setTab} options={tabs} />
      </div>
      {tab === "overview" &&
        (p.positions.length === 0 ? (
          <Panel>
            <EmptyState title="No holdings yet">
              {p.cash != null && `You have ${rupees(p.cash)} of virtual cash. `}Search a stock above and place your
              first order; orders placed while the market is closed fill when it opens.
            </EmptyState>
          </Panel>
        ) : (
          <>
            <ReviewSection id={p.id} period={period} setPeriod={setPeriod} />
            <Panel title="Holdings" meta={`Priced ${fmtStamp(p.priced_at)}`}>
              <Positions p={p} onSell={sell} />
            </Panel>
          </>
        ))}
      {tab !== "overview" &&
        (activity.isPending ? (
          <Panel>
            <SkeletonRows rows={4} />
          </Panel>
        ) : activity.isError ? (
          <Panel>
            <ErrorState error={activity.error} />
          </Panel>
        ) : (
          <Panel
            title={tab === "orders" ? "Orders" : tab === "journal" ? "Decision journal" : "Your scorecard"}
            meta={
              tab === "journal"
                ? "Why you bought, and what came of it against the NIFTY 50"
                : tab === "scorecard"
                  ? "From your closed trades, net of every charge"
                  : undefined
            }
          >
            {tab === "orders" && <OrdersList pid={p.id} orders={activity.data.orders} />}
            {tab === "journal" && <Journal entries={activity.data.journal} />}
            {tab === "scorecard" && <ScorecardView a={activity.data} />}
          </Panel>
        ))}
      <p className="text-2xs text-faint">
        Paper trading with virtual money: orders fill against live NSE prices and are never sent to a broker. Charges
        follow the NSE delivery schedule. Research and education only; not investment advice.
      </p>
    </>
  );
}

export function TrackedPortfolioPage() {
  const { id } = useParams<{ id: string }>();
  const pf = useQuery({
    queryKey: ["tracked", id],
    queryFn: () => api.trackedPortfolio(id!),
    enabled: !!id,
    refetchInterval: 30_000,
  });
  const [period, setPeriod] = useState<ReviewPeriod | null>(null);
  const [adding, setAdding] = useState(false);
  useMarkViewedOnLeave(pf.isSuccess ? id : undefined);

  if (pf.isPending) {
    return (
      <div className="mx-auto max-w-[1200px] p-3 sm:p-4">
        <Panel>
          <SkeletonRows rows={5} />
        </Panel>
      </div>
    );
  }
  if (pf.isError) {
    return (
      <div className="mx-auto max-w-[1200px] p-3 sm:p-4">
        <Panel>
          <ErrorState error={pf.error} />
        </Panel>
      </div>
    );
  }
  const p = pf.data;
  const empty = p.positions.length === 0;
  // Opened before: start with what changed since then. Never opened: since it began.
  const shown = period ?? (p.last_viewed_at ? "last_visit" : "start");

  return (
    <div className="mx-auto flex max-w-[1200px] flex-col gap-4 p-3 sm:p-4">
      <Header p={p} />
      {p.kind === "paper" ? (
        <PaperAccount p={p} period={shown} setPeriod={setPeriod} />
      ) : empty ? (
        <Panel title="Add your first stock">
          <div className="p-3.5">
            <AddStock portfolioId={p.id} />
          </div>
        </Panel>
      ) : (
        <>
          <ReviewSection id={p.id} period={shown} setPeriod={setPeriod} />
          <Panel
            title="Holdings"
            meta={`Priced ${fmtStamp(p.priced_at)}`}
            actions={
              <button
                onClick={() => setAdding((v) => !v)}
                className={cx(
                  "h-7 rounded-md border px-2.5 text-xs font-medium",
                  adding ? "border-line text-muted" : "border-accent/50 text-accent hover:bg-accent-soft",
                )}
              >
                {adding ? "Close" : "Add stock"}
              </button>
            }
          >
            {adding && (
              <div className="border-b border-line p-3.5">
                <AddStock portfolioId={p.id} onDone={() => setAdding(false)} />
              </div>
            )}
            <Positions p={p} />
          </Panel>
        </>
      )}
      {p.kind !== "paper" && !empty && (
        <p className="text-2xs text-faint">
          Explanations split each stock's move into the market, its sector and the stock itself, and list what was
          reported around its big days. Research and education only; not investment advice.
        </p>
      )}
      {p.kind !== "paper" && empty && (
        <EmptyState title="Nothing to review yet">
          Once the portfolio has stocks, this page explains each visit what changed and why.
        </EmptyState>
      )}
    </div>
  );
}
