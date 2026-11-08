import { Ring } from "../../components/ui/visual";
import { HeaderStat, PageHeader, secStyle } from "../../components/PageHeader";
import { toast } from "../../lib/toast";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { EquityChart, type EquityLine } from "../../components/charts/EquityChart";
import { Term } from "../../components/Term";
import { EmptyState, ErrorState, Panel, cx } from "../../components/ui/primitives";
import { api } from "../../lib/api";
import { fmtPrice } from "../../lib/format";
import type { BacktestResult, BacktestSymbol, SavedStrategy, StrategyRules } from "../../lib/types";
import { pct, rupees } from "../portfolio/format";
import { Signed } from "../tracker/PortfoliosPage";
import { SymbolPicker } from "../tracker/paper/OrderTicket";
import { fmtDay } from "../tracker/StockStory";
import { PRESETS, RuleBuilder, field } from "./RuleBuilder";

function Stat({ label, children, sub }: { label: React.ReactNode; children: React.ReactNode; sub?: string }) {
  return (
    <div className="min-w-0">
      <div className="text-2xs tracking-wide text-faint uppercase">{label}</div>
      <div className="num mt-0.5 text-sm font-medium text-fg">{children}</div>
      {sub && <div className="text-2xs text-faint">{sub}</div>}
    </div>
  );
}

function SymbolResultView({ r }: { r: BacktestSymbol }) {
  const lines = useMemo<EquityLine[]>(
    () => [
      { label: "Rules", points: r.equity, tone: "accent" },
      { label: "Buy and hold", points: r.hold, tone: "muted" },
      ...(r.index.length ? [{ label: "NIFTY 50", points: r.index, tone: "faint" as const, dashed: true }] : []),
    ],
    [r],
  );
  const [all, setAll] = useState(false);
  const trades = all ? r.trades : r.trades.slice(-8);
  return (
    <div className="flex flex-col gap-4 p-3.5">
      <p className="text-sm text-fg">{r.verdict}</p>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4 lg:grid-cols-8">
        <Stat label="Rules">
          <Signed v={r.total_return}>{pct(r.total_return, 1, true)}</Signed>
        </Stat>
        <Stat label={<Term k="buy-and-hold">Buy and hold</Term>}>
          <Signed v={r.hold_return}>{pct(r.hold_return, 1, true)}</Signed>
        </Stat>
        <Stat label={<Term k="NIFTY 50">NIFTY 50</Term>}>
          <Signed v={r.index_return}>{pct(r.index_return, 1, true)}</Signed>
        </Stat>
        <Stat label={<Term k="CAGR">CAGR</Term>}>{pct(r.cagr, 1, true)}</Stat>
        <Stat label={<Term k="drawdown">Max drawdown</Term>}>
          <Signed v={r.max_drawdown}>{pct(r.max_drawdown, 1)}</Signed>
        </Stat>
        <Stat label="Trades" sub={r.open_trade ? "last one still open" : undefined}>
          {r.trades.filter((t) => t.exit_reason !== "still held").length}
        </Stat>
        <Stat label={<Term k="win rate">Win rate</Term>}>
          <span className="flex items-center gap-1.5">
            <Ring value={r.win_rate} size={22} stroke={3} tone={(r.win_rate ?? 0) >= 0.5 ? "up" : "caution"} />
            {pct(r.win_rate, 0)}
          </span>
        </Stat>
        <Stat label={<Term k="exposure">In the market</Term>} sub={`charges ₹${r.charges.toFixed(0)}`}>
          <span className="flex items-center gap-1.5">
            <Ring value={r.exposure} size={22} stroke={3} tone="accent" />
            {pct(r.exposure, 0)}
          </span>
        </Stat>
      </div>
      <EquityChart lines={lines} height={260} />
      <p className="text-2xs text-faint">
        Growth of ₹100 from {fmtDay(r.start)} {r.start.slice(0, 4)} to {fmtDay(r.end)} {r.end.slice(0, 4)}.
      </p>
      {r.segments.length > 0 && (
        <div>
          <h3 className="mb-1 text-2xs font-semibold tracking-wide text-faint uppercase">
            <Term k="out-of-sample">Does it hold up on later years?</Term>
          </h3>
          <table className="w-full max-w-xl text-xs">
            <thead>
              <tr className="text-2xs text-faint">
                <th className="px-2 py-1 text-left font-medium">Period</th>
                <th className="px-2 py-1 text-right font-medium">Rules</th>
                <th className="px-2 py-1 text-right font-medium">Hold</th>
                <th className="px-2 py-1 text-right font-medium">Trades</th>
              </tr>
            </thead>
            <tbody>
              {r.segments.map((s) => (
                <tr key={s.label} className="border-t border-line">
                  <td className="px-2 py-1.5 text-fg">
                    {s.label}{" "}
                    <span className="text-faint">
                      ({fmtDay(s.start)} {s.start.slice(0, 4)} – {fmtDay(s.end)} {s.end.slice(0, 4)})
                    </span>
                  </td>
                  <td className="px-2 py-1.5 text-right">
                    <Signed v={s.strategy_return}>{pct(s.strategy_return, 1, true)}</Signed>
                  </td>
                  <td className="px-2 py-1.5 text-right">
                    <Signed v={s.hold_return}>{pct(s.hold_return, 1, true)}</Signed>
                  </td>
                  <td className="num px-2 py-1.5 text-right">{s.trades}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {r.trades.length > 0 && (
        <div className="overflow-x-auto">
          <h3 className="mb-1 text-2xs font-semibold tracking-wide text-faint uppercase">
            Trades {r.trades.length > 8 && !all && `(last 8 of ${r.trades.length})`}
          </h3>
          <table className="w-full min-w-[620px] text-xs">
            <thead>
              <tr className="text-2xs text-faint">
                <th className="px-2 py-1 text-left font-medium">Bought</th>
                <th className="px-2 py-1 text-right font-medium">At</th>
                <th className="px-2 py-1 text-left font-medium">Sold</th>
                <th className="px-2 py-1 text-right font-medium">At</th>
                <th className="px-2 py-1 text-left font-medium">Why</th>
                <th className="px-2 py-1 text-right font-medium">Days</th>
                <th className="px-2 py-1 text-right font-medium">Result</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((t, k) => (
                <tr key={k} className="border-t border-line">
                  <td className="px-2 py-1.5">
                    {fmtDay(t.entry_date)} {t.entry_date.slice(0, 4)}
                  </td>
                  <td className="num px-2 py-1.5 text-right">{fmtPrice(t.entry_price)}</td>
                  <td className="px-2 py-1.5">
                    {t.exit_reason === "still held" ? "—" : `${fmtDay(t.exit_date)} ${t.exit_date.slice(0, 4)}`}
                  </td>
                  <td className="num px-2 py-1.5 text-right">{fmtPrice(t.exit_price)}</td>
                  <td className="px-2 py-1.5 text-muted">{t.exit_reason}</td>
                  <td className="num px-2 py-1.5 text-right">{t.days}</td>
                  <td className="px-2 py-1.5 text-right">
                    <Signed v={t.return_pct}>{pct(t.return_pct, 1, true)}</Signed>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {r.trades.length > 8 && (
            <button onClick={() => setAll((v) => !v)} className="mt-1 text-xs text-muted hover:text-fg">
              {all ? "Show fewer" : "Show all trades"}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function Results({ res, onSave, saving }: { res: BacktestResult; onSave: (name: string) => void; saving: boolean }) {
  const [sel, setSel] = useState(0);
  const [name, setName] = useState("");
  const r = res.results[Math.min(sel, res.results.length - 1)];
  return (
    <Panel title="Backtest result">
      <div className="flex flex-col gap-3 border-b border-line p-3.5">
        <ul className="space-y-0.5 text-xs text-muted">
          {res.rules_text.map((t) => (
            <li key={t}>{t}</li>
          ))}
        </ul>
        <p className="text-sm font-medium text-fg">{res.summary}</p>
        {res.skipped.map((s) => (
          <p key={s} className="text-2xs text-caution">
            {s}
          </p>
        ))}
        <form
          className="flex flex-wrap items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (name.trim()) onSave(name.trim());
          }}
        >
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={60}
            placeholder="Name these rules to save them"
            className={cx(field, "w-64")}
          />
          <button
            type="submit"
            disabled={!name.trim() || saving}
            className="h-8 rounded-md border border-accent/50 px-3 text-xs font-medium text-accent hover:bg-accent-soft disabled:opacity-50"
          >
            Save strategy
          </button>
          <span className="text-2xs text-faint">Saved strategies can run forward in a paper account.</span>
        </form>
      </div>
      {res.results.length > 1 && (
        <div className="flex flex-wrap gap-1.5 border-b border-line px-3.5 py-2">
          {res.results.map((x, i) => (
            <button
              key={x.symbol}
              onClick={() => setSel(i)}
              className={cx(
                "rounded-md border px-2 py-1 text-xs",
                i === sel ? "border-accent bg-accent-soft text-fg" : "border-line text-muted hover:text-fg",
              )}
            >
              {x.symbol}{" "}
              <Signed v={x.total_return - x.hold_return}>{x.total_return > x.hold_return ? "▲" : "▼"}</Signed>
            </button>
          ))}
        </div>
      )}
      {r ? <SymbolResultView key={r.symbol} r={r} /> : <EmptyState title="No stock could be tested" />}
      <ul className="list-disc space-y-0.5 border-t border-line px-7 py-3 text-2xs text-faint">
        {res.assumptions.map((a) => (
          <li key={a}>{a}</li>
        ))}
      </ul>
    </Panel>
  );
}

function StrategyCard({ s }: { s: SavedStrategy }) {
  const qc = useQueryClient();
  const accounts = useQuery({ queryKey: ["tracked"], queryFn: api.tracked });
  const paper = (accounts.data ?? []).filter((p) => p.kind === "paper");
  const [pid, setPid] = useState("");
  const [amount, setAmount] = useState("20000");
  const refresh = () => void qc.invalidateQueries({ queryKey: ["strategies"] });
  const start = useMutation({
    mutationFn: () => api.startStrategy(s.id, { portfolio_id: pid || paper[0]?.id || "", per_trade: Number(amount) }),
    onSuccess: (x) => {
      refresh();
      toast(`${x.name} is running`, {
        body: `It checks the rules after each close and trades ${rupees(x.per_trade)} at a time in ${x.portfolio_name}.`,
      });
    },
  });
  const stop = useMutation({
    mutationFn: () => api.stopStrategy(s.id),
    onSuccess: (x) => {
      refresh();
      toast(`${x.name} stopped`, { tone: "info", body: "Anything it bought stays in the account until you sell." });
    },
  });
  const remove = useMutation({
    mutationFn: () => api.deleteStrategy(s.id),
    onSuccess: () => {
      refresh();
      toast(`Deleted ${s.name}`, { tone: "info" });
    },
  });
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-line bg-surface p-3.5">
      <div className="flex items-center gap-2">
        <h3 className="text-sm font-semibold text-fg">{s.name}</h3>
        <span
          className={cx(
            "rounded px-1.5 py-0.5 text-2xs font-medium",
            s.active ? "bg-up/15 text-up" : "bg-surface-3 text-muted",
          )}
        >
          {s.active ? `Running in ${s.portfolio_name ?? "a paper account"}` : "Not running"}
        </span>
        <button
          onClick={() => {
            if (window.confirm(`Delete "${s.name}"?`)) remove.mutate();
          }}
          className="ml-auto text-2xs text-faint hover:text-down"
        >
          Delete
        </button>
      </div>
      <ul className="space-y-0.5 text-xs text-muted">
        {s.rules_text.map((t) => (
          <li key={t}>{t}</li>
        ))}
      </ul>
      <div className="text-2xs text-faint">Stocks: {s.symbols.join(", ")}</div>
      {s.last_note && <div className="text-2xs text-muted">{s.last_note}</div>}
      {s.active ? (
        <div className="flex items-center gap-3 text-xs">
          <span className="text-muted">{rupees(s.per_trade)} per trade · checked after each close</span>
          <button onClick={() => stop.mutate()} className="text-down hover:underline">
            Stop
          </button>
        </div>
      ) : paper.length === 0 ? (
        <p className="text-2xs text-faint">Create a paper trading account to run this strategy forward.</p>
      ) : (
        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            start.mutate();
          }}
        >
          <label className="flex flex-col gap-1 text-2xs text-faint">
            Paper account
            <select value={pid || paper[0]?.id} onChange={(e) => setPid(e.target.value)} className={field}>
              {paper.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-2xs text-faint">
            Per trade (₹)
            <input
              type="number"
              min={1000}
              step={1000}
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              className={cx(field, "w-28")}
            />
          </label>
          <button type="submit" className="h-8 rounded-md bg-accent px-3 text-xs font-medium text-white">
            Run forward on paper
          </button>
          {start.isError && <span className="text-2xs text-down">{(start.error as Error).message}</span>}
        </form>
      )}
    </div>
  );
}

export function LabPage() {
  const qc = useQueryClient();
  const [symbols, setSymbols] = useState<string[]>(["RELIANCE", "INFY", "HDFCBANK"]);
  const [rules, setRules] = useState<StrategyRules>(PRESETS[0]!.rules);
  const [years, setYears] = useState(5);
  const [capital, setCapital] = useState("100000");
  const [plan, setPlan] = useState("zero");
  const [preset, setPreset] = useState(PRESETS[0]!.name);
  const run = useMutation({
    mutationFn: () => api.backtest({ symbols, rules, years, capital: Number(capital), plan }),
  });
  const save = useMutation({
    mutationFn: (name: string) => api.saveStrategy({ name, rules, symbols }),
    onSuccess: (x) => {
      void qc.invalidateQueries({ queryKey: ["strategies"] });
      toast(`Saved ${x.name}`, { body: "Find it under Saved strategies. You can run it forward on paper." });
    },
  });
  const saved = useQuery({ queryKey: ["strategies"], queryFn: api.strategies, refetchInterval: 60_000 });

  return (
    <div className="mx-auto flex max-w-[1200px] flex-col gap-4 p-3 sm:p-4">
      <PageHeader
        section="lab"
        eyebrow="Experiment safely"
        title="Strategy Lab"
        subtitle="Turn a hunch into rules, test them on up to ten years of real prices with charges, check them on later years they never saw, then let them trade on paper."
      >
        {saved.data && <HeaderStat label="Saved">{saved.data.length}</HeaderStat>}
        {saved.data && <HeaderStat label="Running">{saved.data.filter((s) => s.active).length}</HeaderStat>}
      </PageHeader>
      <Panel title="Rules">
        <div className="flex flex-col gap-4 p-3.5">
          <div>
            <div className="mb-2 text-xs font-medium text-muted">Start from a classic idea, then make it yours</div>
            <div className="fc-stagger grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-4">
              {PRESETS.map((p) => (
                <button
                  key={p.name}
                  onClick={() => {
                    setPreset(p.name);
                    setRules(p.rules);
                  }}
                  className={cx(
                    "fc-card flex flex-col gap-1 rounded-lg border p-3 text-left",
                    preset === p.name
                      ? "border-[var(--sec)] bg-[color-mix(in_srgb,var(--sec)_10%,transparent)]"
                      : "border-line hover:border-line-strong",
                  )}
                  style={secStyle("lab")}
                >
                  <span className="flex items-center gap-2 text-sm font-medium text-fg">
                    <span
                      className={cx("h-2 w-2 rounded-full", preset === p.name ? "bg-[var(--sec)]" : "bg-line-strong")}
                    />
                    {p.name}
                  </span>
                  <span className="text-2xs leading-relaxed text-muted">{p.about}</span>
                </button>
              ))}
            </div>
          </div>
          <RuleBuilder
            rules={rules}
            onChange={(r) => {
              setRules(r);
              setPreset("");
            }}
          />
          <div className="flex flex-col gap-2">
            <h3 className="text-2xs font-semibold tracking-wide text-faint uppercase">Test on (up to 10 stocks)</h3>
            <div className="flex flex-wrap items-center gap-1.5">
              {symbols.map((s) => (
                <span
                  key={s}
                  className="inline-flex items-center gap-1 rounded-full border border-line px-2 py-0.5 text-xs"
                >
                  {s}
                  <button
                    onClick={() => setSymbols(symbols.filter((x) => x !== s))}
                    className="text-faint hover:text-down"
                    aria-label={`Remove ${s}`}
                  >
                    ✕
                  </button>
                </span>
              ))}
              {symbols.length < 10 && (
                <div className="w-56">
                  <SymbolPicker value="" onPick={(s) => s && !symbols.includes(s) && setSymbols([...symbols, s])} />
                </div>
              )}
            </div>
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex flex-col gap-1 text-2xs text-faint">
              Years of history
              <select value={years} onChange={(e) => setYears(Number(e.target.value))} className={field}>
                {[1, 2, 3, 5, 7, 10].map((y) => (
                  <option key={y} value={y}>
                    {y} year{y > 1 ? "s" : ""}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-2xs text-faint">
              Capital per stock (₹)
              <input
                type="number"
                min={10000}
                step={10000}
                value={capital}
                onChange={(e) => setCapital(e.target.value)}
                className={cx(field, "w-32")}
              />
            </label>
            <label className="flex flex-col gap-1 text-2xs text-faint">
              Brokerage
              <select value={plan} onChange={(e) => setPlan(e.target.value)} className={field}>
                <option value="zero">Zero on delivery</option>
                <option value="flat20">₹20 or 0.1% per order</option>
              </select>
            </label>
            <button
              onClick={() => run.mutate()}
              disabled={!symbols.length || run.isPending}
              className="h-8 rounded-md bg-accent px-4 text-sm font-medium text-white disabled:opacity-50"
            >
              {run.isPending ? "Testing…" : "Run backtest"}
            </button>
          </div>
          {run.isPending && (
            <p className="text-2xs text-faint">The first run of a stock downloads ten years of daily prices.</p>
          )}
        </div>
      </Panel>
      {run.isError && (
        <Panel>
          <ErrorState error={run.error} />
        </Panel>
      )}
      {run.data && <Results res={run.data} onSave={(n) => save.mutate(n)} saving={save.isPending} />}
      {save.isError && <p className="text-xs text-down">{(save.error as Error).message}</p>}
      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-semibold tracking-tight text-fg">Saved strategies</h2>
        {saved.data?.length ? (
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            {saved.data.map((s) => (
              <StrategyCard key={s.id} s={s} />
            ))}
          </div>
        ) : (
          <p className="text-xs text-faint">
            Run a backtest and save the rules. A saved strategy can then trade forward in a paper account: rules are
            checked after each close and orders fill at the next open, just as in the backtest.
          </p>
        )}
      </section>
      <p className="text-2xs text-faint">
        Backtests use exchange prices adjusted for splits and bonuses. Past results do not predict future ones. Research
        and education only; not investment advice.
      </p>
    </div>
  );
}
