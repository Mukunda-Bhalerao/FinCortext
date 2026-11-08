import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { EmptyState, ErrorState, Panel, Segmented, SkeletonRows, cx } from "../../components/ui/primitives";
import { api } from "../../lib/api";
import { fmtAgo } from "../../lib/format";
import { useMarketOpen } from "../../lib/queries";
import type { TrackedPortfolioRow } from "../../lib/types";
import { pct, rupees } from "../portfolio/format";

export function Signed({
  v,
  children,
  className,
}: {
  v: number | null | undefined;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cx(
        "num",
        v == null ? "text-faint" : v > 0 ? "text-up" : v < 0 ? "text-down" : "text-muted",
        className,
      )}
    >
      {children}
    </span>
  );
}

function KindBadge({ kind }: { kind: TrackedPortfolioRow["kind"] }) {
  return (
    <span
      className={cx(
        "rounded px-1.5 py-0.5 text-2xs font-medium",
        kind === "paper" ? "bg-accent-soft text-accent" : "bg-surface-3 text-muted",
      )}
    >
      {kind === "paper" ? "Paper trading" : "Tracker"}
    </span>
  );
}

function Cell({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="text-2xs tracking-wide text-faint uppercase">{label}</div>
      <div className="mt-0.5 truncate text-sm">{children}</div>
    </div>
  );
}

function PortfolioCard({ p }: { p: TrackedPortfolioRow }) {
  const marketOpen = useMarketOpen();
  const paper = p.kind === "paper";
  return (
    <Link
      to={`/portfolios/${p.id}`}
      className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4 transition-colors hover:border-line-strong hover:bg-surface-2"
    >
      <div className="flex items-center gap-2">
        <h2 className="truncate text-sm font-semibold text-fg">{p.name}</h2>
        <KindBadge kind={p.kind} />
        <span className="ml-auto shrink-0 text-2xs text-faint">
          {p.positions} {p.positions === 1 ? "stock" : "stocks"}
        </span>
      </div>
      {paper ? (
        <div className="grid grid-cols-3 gap-3">
          <Cell label="Account">
            <span className="num text-fg">{rupees(p.account_value)}</span>
          </Cell>
          <Cell label="Return">
            <Signed v={p.account_return}>{pct(p.account_return, 2, true)}</Signed>
          </Cell>
          <Cell label="Cash">
            <span className="num text-fg">{rupees(p.cash)}</span>
          </Cell>
        </div>
      ) : p.positions === 0 ? (
        <p className="text-xs text-faint">No stocks yet. Open it to add some.</p>
      ) : (
        <div className="grid grid-cols-3 gap-3">
          <Cell label="Value">
            <span className="num text-fg">{rupees(p.value)}</span>
          </Cell>
          <Cell label="Gain">
            <Signed v={p.pnl}>{pct(p.pnl_pct, 1, true)}</Signed>
          </Cell>
          <Cell label={marketOpen ? "Today" : "Last session"}>
            <Signed v={p.day_change_pct}>{pct(p.day_change_pct, 2, true)}</Signed>
          </Cell>
        </div>
      )}
      <div className="text-2xs text-faint">
        {p.last_viewed_at ? `Last opened ${fmtAgo(p.last_viewed_at)}` : `Created ${fmtAgo(p.created_at)}`}
      </div>
    </Link>
  );
}

const input =
  "h-8 rounded-md border border-line bg-surface-2 px-2.5 text-sm text-fg placeholder:text-faint focus:border-accent focus:outline-none";

function CreateForm({ onDone }: { onDone: () => void }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [kind, setKind] = useState<"paper" | "tracking">("paper");
  const [name, setName] = useState("");
  const [cash, setCash] = useState("100000");
  const [plan, setPlan] = useState<"zero" | "flat20">("zero");
  const create = useMutation({
    mutationFn: () =>
      api.createTracked({
        name: name.trim(),
        kind,
        starting_cash: kind === "paper" ? Number(cash) : null,
        plan,
      }),
    onSuccess: (p) => {
      void qc.invalidateQueries({ queryKey: ["tracked"] });
      onDone();
      navigate(`/portfolios/${p.id}`);
    },
  });
  const cashOk = kind === "tracking" || (Number(cash) >= 10_000 && Number(cash) <= 1e9);
  return (
    <form
      className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4"
      onSubmit={(e) => {
        e.preventDefault();
        if (name.trim() && cashOk) create.mutate();
      }}
    >
      <Segmented
        value={kind}
        onChange={setKind}
        options={[
          { value: "paper", label: "Paper trading account" },
          { value: "tracking", label: "Track stocks I own" },
        ]}
      />
      <p className="text-xs text-muted">
        {kind === "paper"
          ? "Start with virtual cash and buy and sell at live prices, with real Indian charges and taxes. Practise and learn before using real money."
          : "Record stocks you already own (at the price and date you bought) and see what happened to them, and why, each time you come back."}
      </p>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <label className="flex flex-col gap-1 text-2xs text-faint">
          Name
          <input
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={60}
            placeholder={kind === "paper" ? "My first practice account" : "Family holdings"}
            className={input}
          />
        </label>
        {kind === "paper" && (
          <>
            <label className="flex flex-col gap-1 text-2xs text-faint">
              Starting cash (₹)
              <input
                type="number"
                min={10000}
                step={1000}
                value={cash}
                onChange={(e) => setCash(e.target.value)}
                className={input}
              />
            </label>
            <label className="flex flex-col gap-1 text-2xs text-faint">
              Brokerage
              <select value={plan} onChange={(e) => setPlan(e.target.value as "zero" | "flat20")} className={input}>
                <option value="zero">Zero on delivery (discount brokers)</option>
                <option value="flat20">₹20 or 0.1% per order, lower of the two</option>
              </select>
            </label>
          </>
        )}
      </div>
      <div className="flex items-center gap-3">
        <button
          type="submit"
          disabled={!name.trim() || !cashOk || create.isPending}
          className="h-8 rounded-md bg-accent px-3 text-sm font-medium text-white disabled:opacity-50"
        >
          Create
        </button>
        <button type="button" onClick={onDone} className="text-xs text-muted hover:text-fg">
          Cancel
        </button>
        {create.isError && <span className="text-xs text-down">{(create.error as Error).message}</span>}
      </div>
    </form>
  );
}

export function PortfoliosPage() {
  const list = useQuery({ queryKey: ["tracked"], queryFn: api.tracked, refetchInterval: 60_000 });
  const [creating, setCreating] = useState(false);
  const paper = list.data?.filter((p) => p.kind === "paper") ?? [];
  const tracking = list.data?.filter((p) => p.kind !== "paper") ?? [];

  return (
    <div className="mx-auto flex max-w-[1200px] flex-col gap-4 p-3 sm:p-4">
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <h1 className="text-lg font-semibold text-fg">Portfolios</h1>
          <p className="text-xs text-muted">
            Practise with paper trading accounts, or track stocks you own. Each visit explains what changed and why.
          </p>
        </div>
        {!creating && (
          <button
            onClick={() => setCreating(true)}
            className="ml-auto h-8 rounded-md bg-accent px-3 text-sm font-medium text-white"
          >
            New portfolio
          </button>
        )}
      </div>
      {creating && <CreateForm onDone={() => setCreating(false)} />}
      {list.isPending ? (
        <Panel>
          <SkeletonRows rows={3} />
        </Panel>
      ) : list.isError ? (
        <Panel>
          <ErrorState error={list.error} />
        </Panel>
      ) : list.data.length === 0 ? (
        <Panel>
          <EmptyState title="No portfolios yet">
            Start a paper trading account with virtual cash: buy and sell at live prices, write down why, and learn from
            what happens. Nothing here uses real money.
          </EmptyState>
        </Panel>
      ) : (
        [
          ["Paper trading", paper],
          ["Trackers", tracking],
        ].map(
          ([title, items]) =>
            (items as TrackedPortfolioRow[]).length > 0 && (
              <section key={title as string} className="flex flex-col gap-2">
                <h2 className="text-xs font-semibold tracking-wide text-fg uppercase">{title as string}</h2>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  {(items as TrackedPortfolioRow[]).map((p) => (
                    <PortfolioCard key={p.id} p={p} />
                  ))}
                </div>
              </section>
            ),
        )
      )}
      <p className="text-2xs text-faint">
        Paper accounts use virtual money; no order is ever sent to a broker. Research and education only.
      </p>
    </div>
  );
}
