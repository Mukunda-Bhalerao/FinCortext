import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { EquityChart, type EquityLine } from "../../components/charts/EquityChart";
import { cx, Panel } from "../../components/ui/primitives";
import { fmtDateIST, fmtNumber, fmtPrice } from "../../lib/format";
import type {
  ObjectiveKey,
  ObjectivePreview,
  PlanAsset,
  PortfolioPlan,
  Preferences,
  RiskSummary,
  StressResult,
  TradePlan,
  YearReturn,
} from "../../lib/types";
import { fmtScore, SignalBadge } from "../research/agents";
import { Tag } from "./evidence";
import { num, pct, rupees, SERIES } from "./format";

export const OBJECTIVE_ORDER: ObjectiveKey[] = ["lower_risk", "balanced", "growth", "income"];

const OBJECTIVE_ICON: Record<ObjectiveKey, string> = {
  lower_risk: "M12 3l7 3v5c0 4.5-3 8-7 10-4-2-7-5.5-7-10V6l7-3z",
  balanced: "M12 3v18M5 7h14M7 7l-3 7h6l-3-7zm10 0l-3 7h6l-3-7z",
  growth: "M3 17l6-6 4 4 8-8M15 7h6v6",
  income: "M12 3v18M16 7.5c0-1.9-1.8-3-4-3s-4 1.1-4 3 1.8 2.6 4 3 4 1.1 4 3-1.8 3-4 3-4-1.1-4-3",
};

/** Stable colour per symbol: the order stocks first appear, never their rank. */
export function useSymbolColors(symbols: string[]): (s: string) => string {
  const key = symbols.join("|");
  return useMemo(() => {
    const map = new Map<string, string>();
    key
      .split("|")
      .filter(Boolean)
      .forEach((s, i) => map.set(s, SERIES[i % SERIES.length] ?? "var(--accent)"));
    return (s: string) => map.get(s) ?? "var(--text-faint)";
  }, [key]);
}

export function ObjectivePicker({
  value,
  previews,
  onChange,
}: {
  value: ObjectiveKey;
  previews: ObjectivePreview[];
  onChange: (k: ObjectiveKey) => void;
}) {
  const byKey = new Map(previews.map((p) => [p.key, p]));
  return (
    <div className="grid grid-cols-2 gap-2 lg:grid-cols-4" role="radiogroup" aria-label="Objective">
      {OBJECTIVE_ORDER.map((k) => {
        const p = byKey.get(k);
        const active = k === value;
        return (
          <button
            key={k}
            role="radio"
            aria-checked={active}
            onClick={() => onChange(k)}
            className={cx(
              "group flex min-w-0 flex-col gap-1.5 rounded-lg border p-3 text-left transition-colors",
              active ? "border-accent bg-accent-soft" : "border-line bg-surface hover:border-line-strong",
            )}
          >
            <span className="flex items-center gap-2">
              <svg
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
                className={active ? "text-accent" : "text-muted group-hover:text-fg"}
                aria-hidden
              >
                <path d={OBJECTIVE_ICON[k]} />
              </svg>
              <span className="text-sm font-semibold text-fg">{p?.label ?? k}</span>
            </span>
            <span className="line-clamp-2 text-2xs leading-snug text-muted">{p?.tagline}</span>
            {p && p.volatility != null && (
              <span className="num mt-auto flex flex-wrap gap-x-3 gap-y-0.5 pt-1 text-2xs text-faint">
                <span title="Estimated yearly volatility, trailing year">Swings {pct(p.volatility, 0)}</span>
                {p.cagr != null && (
                  <span title="Measured: walk-forward backtest, after costs, before tax">
                    Past {pct(p.cagr, 1, true)}/yr
                  </span>
                )}
                {p.max_drawdown != null && <span title="Worst fall from a peak">Worst {pct(p.max_drawdown, 0)}</span>}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

function AllocationBar({ assets, color }: { assets: PlanAsset[]; color: (s: string) => string }) {
  return (
    <div className="flex h-9 w-full gap-0.5 overflow-hidden rounded-md" role="img" aria-label="Allocation">
      {assets.map((a) => (
        <div
          key={a.symbol}
          className="relative h-full min-w-[3px] transition-[width] duration-500 ease-out first:rounded-l-md last:rounded-r-md"
          style={{ width: `${a.weight * 100}%`, background: color(a.symbol) }}
          title={`${a.symbol}: ${pct(a.weight)} of money, ${pct(a.risk_share)} of risk`}
        >
          {a.weight >= 0.09 && (
            <span className="absolute inset-0 flex items-center justify-center truncate px-1 text-2xs font-semibold text-white mix-blend-normal [text-shadow:0_1px_2px_rgba(0,0,0,.35)]">
              {a.symbol}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}

function AssetRows({
  plan,
  color,
  onRemove,
}: {
  plan: PortfolioPlan;
  color: (s: string) => string;
  onRemove: (a: PlanAsset) => void;
}) {
  return (
    <ul className="divide-y divide-line">
      {plan.assets.map((a) => (
        <li key={a.symbol} className="grid grid-cols-[auto_1fr_auto] items-center gap-x-3 gap-y-1 py-2">
          <span className="h-3 w-3 rounded-sm" style={{ background: color(a.symbol) }} aria-hidden />
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-x-2">
              <Link
                to={`/stock/${encodeURIComponent(a.symbol)}`}
                className="text-sm font-medium text-fg hover:text-accent"
              >
                {a.symbol}
              </Link>
              {a.role === "added" && (
                <span className="rounded border border-accent/40 px-1 text-[10px] font-medium text-accent uppercase">
                  Trying
                </span>
              )}
              {a.research_signal && (
                <span className="inline-flex items-center gap-1" title="Research composite (observed)">
                  <SignalBadge signal={a.research_signal} compact />
                  <span className="num text-2xs text-faint">{fmtScore(a.research_score)}</span>
                </span>
              )}
            </div>
            <div className="truncate text-2xs text-faint">
              {a.sector} · swings {pct(a.volatility, 0)}
              {a.dividend_yield != null && a.dividend_yield > 0 && ` · yield ${pct(a.dividend_yield)}`}
              {a.momentum != null && ` · 11-month trend ${pct(a.momentum, 0, true)}`}
            </div>
          </div>
          <div className="flex items-center gap-3">
            <div className="text-right">
              <div className="num text-sm font-medium text-fg">{pct(a.weight)}</div>
              <div className="num text-2xs text-faint" title="Share of portfolio risk">
                risk {pct(a.risk_share, 0)}
              </div>
            </div>
            <button
              onClick={() => onRemove(a)}
              className="flex h-6 w-6 items-center justify-center rounded text-faint hover:bg-surface-2 hover:text-fg"
              aria-label={a.role === "added" ? `Stop trying ${a.symbol}` : `Leave ${a.symbol} out`}
              title={a.role === "added" ? "Stop trying" : "Leave out of the plan"}
            >
              <svg
                width="12"
                height="12"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth="2"
                fill="none"
                aria-hidden
              >
                <path d="M6 6l12 12M18 6L6 18" />
              </svg>
            </button>
          </div>
        </li>
      ))}
    </ul>
  );
}

const LEVELS: RiskSummary["level"][] = ["low", "moderate", "high", "very_high"];
const LEVEL_LABEL = { low: "Low", moderate: "Moderate", high: "High", very_high: "Very high" };

function RiskMeter({ risk }: { risk: RiskSummary }) {
  const ratio = risk.benchmark_volatility ? risk.volatility / risk.benchmark_volatility : 1;
  const pos = Math.min(100, Math.max(0, ((ratio - 0.5) / 1.5) * 100));
  const nifty = ((1 - 0.5) / 1.5) * 100;
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-2xs tracking-wide text-faint uppercase">Risk level</span>
        <Tag kind="estimate" />
      </div>
      <div className="mt-1 text-lg font-semibold text-fg">{LEVEL_LABEL[risk.level]}</div>
      <p className="text-xs text-muted">
        Typical yearly swing of about <span className="num text-fg">±{pct(risk.volatility, 0)}</span>, {risk.level_text}
        .
      </p>
      <div className="relative mt-3 h-2 rounded-full bg-surface-3">
        <div
          className="absolute inset-y-0 left-0 rounded-full bg-accent/40 transition-[width] duration-500"
          style={{ width: `${pos}%` }}
        />
        <div
          className="absolute -top-1 h-4 w-1 -translate-x-1/2 rounded bg-accent transition-[left] duration-500"
          style={{ left: `${pos}%` }}
        />
        <div className="absolute -top-1.5 h-5 w-px bg-line-strong" style={{ left: `${nifty}%` }} title="NIFTY 50" />
      </div>
      <div className="mt-1 flex justify-between text-[10px] text-faint">
        {LEVELS.map((l) => (
          <span key={l} className={l === risk.level ? "font-medium text-fg" : undefined}>
            {LEVEL_LABEL[l]}
          </span>
        ))}
      </div>
    </div>
  );
}

function DiversificationMeter({ risk, n }: { risk: RiskSummary; n: number }) {
  const removed = 1 - 1 / risk.diversification_ratio;
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-2xs tracking-wide text-faint uppercase">Diversification</span>
        <Tag kind="estimate" />
      </div>
      <div className="mt-1 flex items-baseline gap-1.5">
        <span className="num text-lg font-semibold text-fg">{risk.diversification_score}</span>
        <span className="text-xs text-faint">/ 100</span>
      </div>
      <p className="text-xs text-muted">
        Mixing these {n} stocks cancels <span className="num text-fg">{pct(removed, 0)}</span> of their individual
        swings. {risk.top_risk_symbol} carries the most risk ({pct(risk.top_risk_share, 0)}).
      </p>
      <div className="mt-3 h-2 rounded-full bg-surface-3">
        <div
          className="h-full rounded-full bg-accent transition-[width] duration-500"
          style={{ width: `${risk.diversification_score}%` }}
        />
      </div>
    </div>
  );
}

function YearBars({ years, label }: { years: YearReturn[]; label: string }) {
  const max = Math.max(0.05, ...years.flatMap((y) => [Math.abs(y.portfolio), Math.abs(y.benchmark ?? 0)]));
  const H = 56;
  return (
    <div>
      <div className="mb-1.5 flex flex-wrap items-center gap-3 text-2xs text-faint">
        <span className="inline-flex items-center gap-1">
          <span className="h-2 w-2 rounded-sm bg-accent" /> Plan
        </span>
        <span className="inline-flex items-center gap-1">
          <span className="h-2 w-2 rounded-sm" style={{ background: "var(--neutral-bar)" }} /> {label}
        </span>
      </div>
      <div className="flex items-stretch gap-1.5 overflow-x-auto pb-1">
        {years.map((y) => (
          <div key={y.year} className="flex min-w-9 flex-1 flex-col items-center">
            <div className="relative w-full" style={{ height: H * 2 }}>
              <div className="absolute inset-x-0 top-1/2 h-px bg-line" />
              {[
                { v: y.portfolio, bg: "var(--accent)", x: "left-[18%]" },
                { v: y.benchmark ?? 0, bg: "var(--neutral-bar)", x: "right-[18%]" },
              ].map((b, i) => {
                const h = (Math.abs(b.v) / max) * H;
                return (
                  <div
                    key={i}
                    className={cx("absolute w-[28%] transition-all duration-500", b.x)}
                    style={{
                      height: Math.max(1, h),
                      background: b.bg,
                      top: b.v >= 0 ? H - h : H,
                      borderRadius: b.v >= 0 ? "3px 3px 0 0" : "0 0 3px 3px",
                    }}
                  />
                );
              })}
              <div
                className="absolute inset-0"
                title={`${y.year}${y.partial ? " (part year)" : ""}: plan ${pct(y.portfolio, 1, true)}, ${label} ${pct(y.benchmark, 1, true)}`}
              />
            </div>
            <span className={cx("num mt-0.5 text-[10px]", y.partial ? "text-faint italic" : "text-muted")}>
              {String(y.year).slice(2)}
              {y.partial && "*"}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function Outcome({ plan }: { plan: PortfolioPlan }) {
  const bt = plan.backtest;
  const [afterTax, setAfterTax] = useState(true);
  const lines = useMemo<EquityLine[]>(() => {
    if (!bt) return [];
    const out: EquityLine[] = [
      {
        label: afterTax && bt.after_tax_curve.length ? "Plan, after tax" : "Plan",
        points: afterTax && bt.after_tax_curve.length ? bt.after_tax_curve : bt.curve,
        tone: "accent",
      },
      { label: bt.benchmark_label, points: bt.benchmark_curve, tone: "muted" },
    ];
    if (bt.baseline_curve.length && bt.baseline_label)
      out.push({ label: bt.baseline_label, points: bt.baseline_curve, tone: "faint", dashed: true });
    return out;
  }, [bt, afterTax]);
  if (!bt) {
    return (
      <Panel title="How it behaved">
        <p className="p-3.5 text-sm text-muted">{plan.backtest_note}</p>
      </Panel>
    );
  }
  const shown = afterTax && bt.after_tax ? bt.after_tax : bt.pre_tax;
  const gap = (bt.pre_tax.cagr ?? 0) - (bt.benchmark.cagr ?? 0);
  const u = bt.uncertainty;
  const final = (lines[0]?.points.at(-1)?.value ?? 1) * plan.preferences.capital;
  return (
    <Panel
      title="How it would have behaved"
      meta={`${fmtDateIST(bt.start)} to ${fmtDateIST(bt.end)} · ${fmtNumber(bt.years, 1)} years`}
      actions={
        <span className="flex items-center gap-2">
          {bt.after_tax && (
            <label className="flex cursor-pointer items-center gap-1.5 text-2xs text-muted">
              <input
                type="checkbox"
                checked={afterTax}
                onChange={(e) => setAfterTax(e.target.checked)}
                className="accent-[var(--accent)]"
              />
              After tax
            </label>
          )}
          <Tag kind="measured" />
        </span>
      }
    >
      <div className="grid grid-cols-1 gap-4 p-3.5 lg:grid-cols-5">
        <div className="space-y-3 lg:col-span-2">
          <p className="text-sm leading-relaxed text-fg">
            {rupees(plan.preferences.capital)} invested on {fmtDateIST(bt.start)} with monthly rebalancing would have
            become <span className="num font-semibold">{rupees(final)}</span>
            {afterTax && bt.after_tax ? " after costs and estimated tax" : " after costs, before tax"}:{" "}
            <span className="num font-semibold">{pct(shown.cagr, 1, true)}</span> a year, against{" "}
            <span className="num">{pct(bt.benchmark.cagr, 1, true)}</span> for {bt.benchmark_label}.
          </p>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
            <div>
              <dt className="text-faint">Worst fall</dt>
              <dd className="num text-fg">
                {pct(shown.max_drawdown, 0)} <span className="text-faint">vs {pct(bt.benchmark.max_drawdown, 0)}</span>
              </dd>
            </div>
            <div>
              <dt className="text-faint">Yearly swings</dt>
              <dd className="num text-fg">
                {pct(shown.volatility, 0)} <span className="text-faint">vs {pct(bt.benchmark.volatility, 0)}</span>
              </dd>
            </div>
            <div>
              <dt className="text-faint">Costs</dt>
              <dd className="num text-fg">{pct(bt.costs_per_year, 2)}/yr</dd>
            </div>
            <div>
              <dt className="text-faint">Tax</dt>
              <dd className="num text-fg">{bt.taxes_per_year != null ? `${pct(bt.taxes_per_year, 2)}/yr` : "—"}</dd>
            </div>
          </dl>
          {u && (
            <div className="rounded-md border border-line bg-surface-2 p-2.5 text-xs leading-relaxed text-muted">
              <span className="font-medium text-fg">How sure is this?</span>{" "}
              {u.excess_low < 0 && u.excess_high > 0
                ? `Not very. Resampling the history puts the yearly gap to the benchmark anywhere from ${pct(u.excess_low, 1, true)} to ${pct(u.excess_high, 1, true)}, so the ${gap >= 0 ? "lead" : "shortfall"} could be luck.`
                : `The ${gap >= 0 ? "lead" : "shortfall"} held in most resamples (${pct(u.excess_low, 1, true)} to ${pct(u.excess_high, 1, true)} a year), but it is still the past with stocks picked today.`}
            </div>
          )}
          {bt.limited_by && <p className="text-2xs text-faint">{bt.limited_by}</p>}
        </div>
        <div className="min-w-0 lg:col-span-3">
          <div className="mb-1 flex flex-wrap gap-x-3 gap-y-1 text-2xs text-muted">
            {lines.map((l) => (
              <span key={l.label} className="inline-flex items-center gap-1.5">
                <span
                  className="inline-block h-0 w-4 border-t-2"
                  style={{
                    borderColor:
                      l.tone === "accent"
                        ? "var(--accent)"
                        : l.tone === "muted"
                          ? "var(--text-muted)"
                          : "var(--text-faint)",
                    borderStyle: l.dashed ? "dashed" : "solid",
                  }}
                />
                {l.label}
              </span>
            ))}
          </div>
          <EquityChart lines={lines} height={220} />
        </div>
      </div>
      <div className="border-t border-line px-3.5 py-3">
        <div className="mb-1 text-2xs tracking-wide text-faint uppercase">Year by year, before tax</div>
        <YearBars years={bt.years_table} label={bt.benchmark_label} />
      </div>
      <p className="border-t border-line px-3.5 py-2 text-2xs text-faint">
        {bt.return_basis} Weights were rebuilt each month from the year before, so no future data was used. The stocks
        were chosen today, which flatters every past result.
      </p>
    </Panel>
  );
}

function StressPanel({ stress }: { stress: StressResult[] }) {
  if (!stress.length) return null;
  const max = Math.max(0.1, ...stress.flatMap((s) => [Math.abs(s.portfolio ?? 0), Math.abs(s.benchmark ?? 0)]));
  return (
    <Panel title="In past sell-offs" actions={<Tag kind="measured" />}>
      <ul className="divide-y divide-line">
        {stress.map((s) => (
          <li key={s.key} className="px-3.5 py-2.5">
            <div className="flex flex-wrap items-baseline justify-between gap-x-3">
              <span className="text-sm font-medium text-fg">{s.name}</span>
              <span className="text-2xs text-faint">
                {fmtDateIST(s.start)} to {fmtDateIST(s.end)}
              </span>
            </div>
            {s.covered ? (
              <div className="mt-1.5 space-y-1">
                {[
                  { label: "Today's plan", v: s.portfolio, bg: "var(--accent)" },
                  { label: "NIFTY 50", v: s.benchmark, bg: "var(--neutral-bar)" },
                ].map((b) => (
                  <div key={b.label} className="grid grid-cols-[84px_1fr_52px] items-center gap-2 text-2xs">
                    <span className="text-muted">{b.label}</span>
                    <div className="h-2 rounded-full bg-surface-3">
                      <div
                        className="h-full rounded-full transition-[width] duration-500"
                        style={{ width: `${(Math.abs(b.v ?? 0) / max) * 100}%`, background: b.bg }}
                      />
                    </div>
                    <span className="num text-right text-fg">{pct(b.v, 1, true)}</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="mt-1 text-2xs text-faint">{s.note}</p>
            )}
          </li>
        ))}
      </ul>
      <p className="border-t border-line px-3.5 py-2 text-2xs text-faint">
        Today's weights replayed through each episode on real prices and dividends. A guide to behaviour in a fall, not
        what this portfolio actually did.
      </p>
    </Panel>
  );
}

function Trades({ trades, onEditHoldings }: { trades: TradePlan; onEditHoldings: () => void }) {
  const moves = trades.lines.filter((l) => l.action !== "hold");
  return (
    <Panel
      title={trades.basis === "holdings" ? "Moves from your holdings" : "To build it from cash"}
      meta={`${rupees(trades.total_value)} · est. charges ${rupees(trades.est_costs)}`}
      actions={
        <button
          onClick={onEditHoldings}
          className="rounded-md border border-line px-2 py-0.5 text-2xs text-muted hover:border-line-strong hover:text-fg"
        >
          {trades.basis === "holdings" ? "Edit holdings" : "Enter my holdings"}
        </button>
      }
    >
      <div className="overflow-x-auto">
        <table className="w-full min-w-[480px] text-left text-sm">
          <thead>
            <tr className="border-b border-line text-2xs tracking-wide text-faint uppercase">
              <th className="px-3.5 py-1.5 font-medium">Stock</th>
              <th className="px-3 py-1.5 text-right font-medium">Now</th>
              <th className="px-3 py-1.5 text-right font-medium">Target</th>
              <th className="px-3.5 py-1.5 text-right font-medium">Change</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {trades.lines.map((l) => (
              <tr key={l.symbol}>
                <td className="px-3.5 py-2">
                  <div className="font-medium text-fg">{l.symbol}</div>
                  <div className="num text-2xs text-faint">{fmtPrice(l.price)}</div>
                </td>
                <td className="num px-3 py-2 text-right text-muted">{pct(l.current_weight, 0)}</td>
                <td className="num px-3 py-2 text-right text-fg">{pct(l.target_weight, 0)}</td>
                <td className="num px-3.5 py-2 text-right">
                  {l.action === "hold" ? (
                    <span className="text-faint">Hold</span>
                  ) : (
                    <span className={l.action === "buy" ? "text-fg" : "text-caution"}>
                      {l.action === "buy" ? "Buy" : "Sell"} {fmtNumber(Math.abs(l.delta_qty), 0)}
                      <span className="block text-2xs text-faint">{rupees(Math.abs(l.delta_value))}</span>
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="border-t border-line px-3.5 py-2 text-2xs text-faint">
        {moves.length === 0 ? "Already close to the plan. " : ""}
        {trades.note}
        {trades.realised_gain != null && ` Selling realises about ${rupees(trades.realised_gain)} of gains.`}
        {trades.basis === "capital" && ` About ${rupees(trades.cash_left)} stays in cash.`} This is a calculation, not
        an order; nothing is sent to a broker.
      </p>
    </Panel>
  );
}

export function PlanWorkbench({
  plan,
  prefs,
  updating,
  onChange,
  onEditHoldings,
}: {
  plan: PortfolioPlan;
  prefs: Preferences;
  updating: boolean;
  onChange: (p: Partial<Preferences>) => void;
  onEditHoldings: () => void;
}) {
  const symbols = useMemo(
    () => [...new Set([...plan.assets.map((a) => a.symbol), ...prefs.exclude])],
    [plan.assets, prefs.exclude],
  );
  const color = useSymbolColors(symbols);
  const risk = plan.risk;
  const cap = prefs.max_weight ?? null;
  const remove = (a: PlanAsset) =>
    a.role === "added"
      ? onChange({ include: prefs.include.filter((s) => s !== a.symbol) })
      : onChange({ exclude: [...prefs.exclude, a.symbol] });
  return (
    <div className={cx("flex flex-col gap-3", updating && "fc-updating")} aria-busy={updating}>
      <div className="grid grid-cols-1 gap-3 xl:grid-cols-5">
        <Panel
          title={`${plan.objective.label}: allocation`}
          meta={plan.objective.method}
          className="xl:col-span-3"
          actions={<Tag kind="estimate" />}
        >
          <div className="space-y-3 p-3.5">
            <AllocationBar assets={plan.assets} color={color} />
            {plan.explanation.length > 0 && (
              <ul className="space-y-1 text-xs leading-relaxed text-muted">
                {plan.explanation.map((e) => (
                  <li key={e} className="flex gap-2">
                    <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-accent" aria-hidden />
                    {e}
                  </li>
                ))}
              </ul>
            )}
            <AssetRows plan={plan} color={color} onRemove={remove} />
            {prefs.exclude.length > 0 && (
              <div className="flex flex-wrap items-center gap-1.5 text-2xs text-faint">
                Left out:
                {prefs.exclude.map((s) => (
                  <button
                    key={s}
                    onClick={() => onChange({ exclude: prefs.exclude.filter((x) => x !== s) })}
                    className="rounded-full border border-line px-2 py-0.5 text-muted hover:border-accent hover:text-accent"
                    title="Put back"
                  >
                    {s} +
                  </button>
                ))}
              </div>
            )}
            {plan.weight_note && <p className="text-2xs text-faint">{plan.weight_note}</p>}
          </div>
          <div className="grid grid-cols-1 gap-3 border-t border-line p-3.5 sm:grid-cols-3">
            <label className="block text-2xs text-faint">
              Amount to plan with
              <input
                type="number"
                min={10000}
                step={10000}
                defaultValue={prefs.capital}
                onBlur={(e) => {
                  const v = Number(e.target.value);
                  if (Number.isFinite(v) && v >= 10000 && v !== prefs.capital) onChange({ capital: v });
                }}
                onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
                className="num mt-1 h-8 w-full rounded-md border border-line bg-surface-2 px-2 text-sm text-fg outline-none focus:border-accent"
              />
            </label>
            <label className="block text-2xs text-faint">
              Most in one stock: <span className="num text-fg">{cap ? pct(cap, 0) : "auto"}</span>
              <input
                type="range"
                min={10}
                max={100}
                step={5}
                value={Math.round((cap ?? 0) * 100) || 100}
                onChange={(e) => {
                  const v = Number(e.target.value);
                  onChange({ max_weight: v >= 100 ? null : v / 100 });
                }}
                className="mt-2.5 w-full accent-[var(--accent)]"
                aria-label="Maximum weight per stock"
              />
            </label>
            <label className="flex items-start gap-2 pt-1 text-2xs text-muted">
              <input
                type="checkbox"
                checked={prefs.research_overlay}
                onChange={(e) => onChange({ research_overlay: e.target.checked })}
                className="mt-0.5 accent-[var(--accent)]"
              />
              <span>
                Let research scores nudge weights
                <span className="block text-faint">Today only; it has no history to test.</span>
              </span>
            </label>
          </div>
        </Panel>
        <div className="flex flex-col gap-3 xl:col-span-2">
          {risk && (
            <Panel title="What this means">
              <div className="space-y-4 p-3.5">
                <RiskMeter risk={risk} />
                <DiversificationMeter risk={risk} n={plan.assets.length} />
                {plan.current && (
                  <div className="rounded-md border border-line bg-surface-2 p-2.5 text-xs text-muted">
                    <div className="mb-1 font-medium text-fg">Compared with {plan.current.label.toLowerCase()}</div>
                    <div className="num grid grid-cols-2 gap-2">
                      <span>
                        Swings {pct(plan.current.volatility, 0)} →{" "}
                        <span className="text-fg">{pct(risk.volatility, 0)}</span>
                      </span>
                      <span>
                        Div. ratio {num(plan.current.diversification_ratio)} →{" "}
                        <span className="text-fg">{num(risk.diversification_ratio)}</span>
                      </span>
                      {plan.current.cagr != null && plan.backtest && (
                        <span className="col-span-2">
                          Past return {pct(plan.current.cagr, 1, true)} →{" "}
                          <span className="text-fg">{pct(plan.backtest.pre_tax.cagr, 1, true)}</span> a year
                        </span>
                      )}
                    </div>
                  </div>
                )}
              </div>
            </Panel>
          )}
          <StressPanel stress={plan.stress} />
        </div>
      </div>
      <Outcome plan={plan} />
      {plan.trades && <Trades trades={plan.trades} onEditHoldings={onEditHoldings} />}
    </div>
  );
}
