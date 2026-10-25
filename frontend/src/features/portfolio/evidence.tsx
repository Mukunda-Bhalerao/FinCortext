import { useMemo, useState } from "react";
import { DASH, num, pct } from "./format";
import { Link } from "react-router-dom";
import { EquityChart, type EquityLine } from "../../components/charts/EquityChart";
import { cx, EmptyState, Panel, Stat } from "../../components/ui/primitives";
import { fmtDateIST } from "../../lib/format";
import type { PerfStats, PortfolioAnalysis, StrategyResult } from "../../lib/types";
import { fmtScore, SignalBadge } from "../research/agents";

const period = (s: PerfStats) => (s.start && s.end ? `${fmtDateIST(s.start)} to ${fmtDateIST(s.end)}` : "");

/** Horizontal share bar in the accent tone. */
function Share({ value }: { value: number }) {
  return (
    <div className="h-1.5 w-full rounded-full bg-surface-3">
      <div className="h-full rounded-full bg-accent" style={{ width: `${Math.min(100, Math.max(0, value * 100))}%` }} />
    </div>
  );
}

export function Tag({ kind }: { kind: "measured" | "estimate" }) {
  return (
    <span
      className={cx(
        "rounded border px-1 text-[10px] font-medium tracking-wide uppercase",
        kind === "measured" ? "border-accent/40 text-accent" : "border-line-strong text-faint",
      )}
    >
      {kind === "measured" ? "Measured" : "Estimate"}
    </span>
  );
}

export function StrategyTable({
  data,
  selected,
  onSelect,
}: {
  data: PortfolioAnalysis;
  selected: string;
  onSelect: (key: string) => void;
}) {
  const bench = data.strategies.find((s) => s.backtest)?.backtest?.benchmark;
  return (
    <Panel
      title="Strategy comparison"
      meta={bench ? `Walk-forward ${period(bench)}` : undefined}
      actions={
        <span className="flex items-center gap-1.5">
          <Tag kind="estimate" />
          <span className="text-2xs text-faint">trailing year, in-sample</span>
          <Tag kind="measured" />
          <span className="text-2xs text-faint">walk-forward, after costs</span>
        </span>
      }
    >
      <div className="overflow-x-auto">
        <table className="w-full min-w-[920px] text-left text-sm">
          <thead>
            <tr className="text-2xs tracking-wide text-faint uppercase">
              <th className="px-3.5 pt-2 font-medium" />
              <th colSpan={4} className="border-l border-line px-3 pt-2 font-medium">
                Estimate · trailing 1Y
              </th>
              <th colSpan={6} className="border-l border-line px-3 pt-2 font-medium">
                Measured · walk-forward
              </th>
            </tr>
            <tr className="border-b border-line text-2xs tracking-wide text-faint uppercase">
              <th className="px-3.5 py-1.5 font-medium">Strategy</th>
              <th className="border-l border-line px-3 py-1.5 text-right font-medium">Volatility</th>
              <th className="px-3 py-1.5 text-right font-medium">Div. ratio</th>
              <th className="px-3 py-1.5 text-right font-medium">Eff. holdings</th>
              <th className="px-3 py-1.5 text-right font-medium">1Y return</th>
              <th className="border-l border-line px-3 py-1.5 text-right font-medium">CAGR</th>
              <th className="px-3 py-1.5 text-right font-medium">Volatility</th>
              <th className="px-3 py-1.5 text-right font-medium">Sharpe</th>
              <th className="px-3 py-1.5 text-right font-medium">Max DD</th>
              <th className="px-3 py-1.5 text-right font-medium">Turnover/yr</th>
              <th className="px-3.5 py-1.5 text-right font-medium">Costs/yr</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {data.strategies.map((s) => {
              const bt = s.backtest;
              return (
                <tr
                  key={s.key}
                  onClick={() => onSelect(s.key)}
                  className={cx("num cursor-pointer", s.key === selected ? "bg-accent-soft" : "hover:bg-surface-2")}
                >
                  <td className="px-3.5 py-2">
                    <div className="font-sans font-medium text-fg">
                      {s.label}
                      {s.key === data.reference_strategy && (
                        <span className="ml-1.5 text-2xs font-normal text-faint">reference</span>
                      )}
                    </div>
                    <div className="max-w-64 truncate font-sans text-2xs text-faint" title={s.description}>
                      {s.description}
                    </div>
                  </td>
                  <td className="border-l border-line px-3 py-2 text-right text-fg">{pct(s.est_volatility)}</td>
                  <td className="px-3 py-2 text-right text-fg">{num(s.diversification_ratio)}</td>
                  <td className="px-3 py-2 text-right text-fg">{num(s.effective_n, 1)}</td>
                  <td className="px-3 py-2 text-right text-muted">{pct(s.trailing.total_return, 1, true)}</td>
                  {bt ? (
                    <>
                      <td className="border-l border-line px-3 py-2 text-right text-fg">
                        {pct(bt.stats.cagr, 1, true)}
                      </td>
                      <td className="px-3 py-2 text-right text-fg">{pct(bt.stats.volatility)}</td>
                      <td className="px-3 py-2 text-right text-fg">{num(bt.stats.sharpe)}</td>
                      <td className="px-3 py-2 text-right text-fg">{pct(bt.stats.max_drawdown)}</td>
                      <td className="px-3 py-2 text-right text-muted">{pct(bt.turnover_per_year, 0)}</td>
                      <td className="px-3.5 py-2 text-right text-muted">{pct(bt.cost_drag_per_year, 2)}</td>
                    </>
                  ) : (
                    <td colSpan={6} className="border-l border-line px-3 py-2 font-sans text-2xs text-faint">
                      {s.backtest_note}
                    </td>
                  )}
                </tr>
              );
            })}
            {bench && (
              <tr className="num text-muted">
                <td className="px-3.5 py-2 font-sans">
                  <div className="font-medium text-muted">{data.benchmark_label} (buy and hold)</div>
                  <div className="text-2xs text-faint">Benchmark, same period</div>
                </td>
                <td colSpan={4} className="border-l border-line px-3 py-2" />
                <td className="border-l border-line px-3 py-2 text-right">{pct(bench.cagr, 1, true)}</td>
                <td className="px-3 py-2 text-right">{pct(bench.volatility)}</td>
                <td className="px-3 py-2 text-right">{num(bench.sharpe)}</td>
                <td className="px-3 py-2 text-right">{pct(bench.max_drawdown)}</td>
                <td className="px-3 py-2 text-right">{DASH}</td>
                <td className="px-3.5 py-2 text-right">{DASH}</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <p className="border-t border-line px-3.5 py-2 text-2xs text-faint">
        Sharpe uses a risk-free rate of {pct(data.risk_free_rate, 2)} ({data.risk_free_source}). Click a strategy for
        its weights and equity curve.
      </p>
    </Panel>
  );
}

export function StrategyDetail({ data, strategy }: { data: PortfolioAnalysis; strategy: StrategyResult }) {
  const holdings = new Map(data.holdings.map((h) => [h.symbol, h]));
  const lines = useMemo<EquityLine[]>(
    () =>
      strategy.backtest
        ? [
            {
              label: strategy.label,
              points: strategy.backtest.curve,
              tone: "accent",
            },
            {
              label: data.benchmark_label,
              points: strategy.backtest.benchmark_curve,
              tone: "muted",
            },
          ]
        : [],
    [strategy],
  );
  const sectors = Object.entries(strategy.sector_weights).sort((a, b) => b[1] - a[1]);
  return (
    <div className="grid grid-cols-1 gap-3 xl:grid-cols-5">
      <Panel
        title={`${strategy.label}: weights`}
        meta={strategy.constraint_note ?? undefined}
        className="xl:col-span-2"
      >
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-line text-2xs tracking-wide text-faint uppercase">
                <th className="px-3.5 py-1.5 font-medium">Stock</th>
                <th className="px-3 py-1.5 font-medium">Weight</th>
                <th className="px-3 py-1.5 text-right font-medium">Risk share</th>
                <th className="px-3.5 py-1.5 text-right font-medium">Research</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {strategy.weights.map((w) => {
                const h = holdings.get(w.symbol);
                return (
                  <tr key={w.symbol}>
                    <td className="px-3.5 py-2">
                      <Link
                        to={`/stock/${encodeURIComponent(w.symbol)}`}
                        className="font-medium text-fg hover:text-accent"
                      >
                        {w.symbol}
                      </Link>
                      <div className="max-w-40 truncate text-2xs text-faint">{h?.sector}</div>
                    </td>
                    <td className="w-28 px-3 py-2 sm:w-40">
                      <div className="num text-xs text-fg">{pct(w.weight)}</div>
                      <Share value={w.weight} />
                    </td>
                    <td className="num px-3 py-2 text-right text-xs text-muted">{pct(w.risk_contribution)}</td>
                    <td className="px-3.5 py-2 text-right">
                      {h?.research_signal ? (
                        <span className="inline-flex items-center gap-1.5">
                          <SignalBadge signal={h.research_signal} compact />
                          <span className="num text-2xs text-muted">{fmtScore(h.research_score)}</span>
                        </span>
                      ) : (
                        <span className="text-2xs text-faint">Not run</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="space-y-1.5 border-t border-line px-3.5 py-3">
          <div className="text-2xs tracking-wide text-faint uppercase">Sector allocation</div>
          {sectors.map(([name, w]) => (
            <div
              key={name}
              className="grid grid-cols-[1fr_80px_48px] items-center gap-2 text-xs sm:grid-cols-[1fr_120px_48px]"
            >
              <span className="truncate text-muted">{name}</span>
              <Share value={w} />
              <span className="num text-right text-fg">{pct(w)}</span>
            </div>
          ))}
        </div>
      </Panel>
      <Panel
        title="Growth of 100"
        meta={strategy.backtest ? `${period(strategy.backtest.stats)} · monthly rebalance, after costs` : undefined}
        className="xl:col-span-3"
      >
        {strategy.backtest ? (
          <div className="p-2">
            <EquityChart lines={lines} />
            <div className="grid grid-cols-2 gap-3 border-t border-line px-1.5 pt-2.5 sm:grid-cols-4">
              <Stat label="Rebalances" value={strategy.backtest.rebalances} />
              <Stat label="Total return" value={pct(strategy.backtest.stats.total_return, 1, true)} sub="Strategy" />
              <Stat
                label="Benchmark"
                value={pct(strategy.backtest.benchmark.total_return, 1, true)}
                sub={data.benchmark_label}
              />
              <Stat label="Costs/yr" value={pct(strategy.backtest.cost_drag_per_year, 2)} sub="Itemised charges" />
            </div>
          </div>
        ) : (
          <EmptyState title="No measured history for this strategy">{strategy.backtest_note}</EmptyState>
        )}
      </Panel>
    </div>
  );
}

export function CorrelationPanel({ data }: { data: PortfolioAnalysis }) {
  const c = data.correlation;
  if (!c) return null;
  return (
    <Panel title="Correlation" meta={`Daily returns, trailing year · average ${num(c.average)}`}>
      <div className="overflow-x-auto p-3">
        <table className="num text-xs">
          <thead>
            <tr>
              <th />
              {c.symbols.map((s) => (
                <th key={s} className="px-1.5 pb-1 font-sans text-2xs font-medium text-faint">
                  {s}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {c.matrix.map((row, i) => (
              <tr key={c.symbols[i]}>
                <th className="pr-2 text-right font-sans text-2xs font-medium text-faint">{c.symbols[i]}</th>
                {row.map((v, j) => (
                  <td
                    key={j}
                    className="h-8 min-w-12 rounded-sm px-1.5 text-center text-fg"
                    style={{
                      background:
                        i === j
                          ? "var(--surface-3)"
                          : `color-mix(in srgb, var(--accent) ${Math.round(Math.max(0, v) * 60)}%, transparent)`,
                    }}
                  >
                    {num(v)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-2 text-2xs text-faint">
          Stronger shading means stocks moved together more; low or negative values diversify.
        </p>
      </div>
    </Panel>
  );
}

export function CandidatesPanel({ data }: { data: PortfolioAnalysis }) {
  const first = data.candidates[0];
  return (
    <Panel
      title="Diversification candidates"
      meta={`${data.candidates_screened} ${data.candidate_universe} stocks screened`}
    >
      {data.candidates.length === 0 ? (
        <EmptyState title="No candidates">
          Candidates need at least one holding with a year of price history.
        </EmptyState>
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[860px] text-left text-sm">
              <thead>
                <tr className="border-b border-line text-2xs tracking-wide text-faint uppercase">
                  <th className="px-3.5 py-1.5 font-medium">Stock</th>
                  <th className="px-3 py-1.5 text-right font-medium">Avg corr.</th>
                  <th className="px-3 py-1.5 text-right font-medium">Weight if added</th>
                  <th className="px-3 py-1.5 text-right font-medium">Est. volatility</th>
                  <th className="px-3 py-1.5 text-right font-medium">Div. ratio</th>
                  <th className="px-3 py-1.5 font-medium">
                    Earlier period <Tag kind="measured" />
                  </th>
                  <th className="px-3.5 py-1.5 text-right font-medium">Research</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {data.candidates.map((c) => (
                  <tr key={c.symbol} className="align-top">
                    <td className="px-3.5 py-2">
                      <Link
                        to={`/stock/${encodeURIComponent(c.symbol)}`}
                        className="font-medium text-fg hover:text-accent"
                      >
                        {c.symbol}
                      </Link>
                      <div className="max-w-56 text-2xs text-faint">
                        {c.sector}
                        {c.new_sector && <span className="ml-1 text-accent">new sector</span>}
                      </div>
                      <p className="mt-1 max-w-md text-2xs leading-relaxed text-muted">{c.explanation}</p>
                    </td>
                    <td className="num px-3 py-2 text-right text-fg">{num(c.avg_correlation)}</td>
                    <td className="num px-3 py-2 text-right text-muted">{pct(c.weight_if_added, 0)}</td>
                    <td className="num px-3 py-2 text-right text-fg">
                      {pct(c.vol_before)} → {pct(c.vol_after)}
                    </td>
                    <td className="num px-3 py-2 text-right text-fg">
                      {num(c.dr_before)} → {num(c.dr_after)}
                    </td>
                    <td className="num px-3 py-2 text-xs text-muted">
                      {c.validation ? (
                        <>
                          <div>
                            Vol {pct(c.validation.vol_without)} → {pct(c.validation.vol_with)}
                          </div>
                          <div>
                            Sharpe {num(c.validation.sharpe_without)} → {num(c.validation.sharpe_with)}
                          </div>
                          <div>
                            Max DD {pct(c.validation.mdd_without)} → {pct(c.validation.mdd_with)}
                          </div>
                        </>
                      ) : (
                        <span className="font-sans text-2xs text-faint">Top five only</span>
                      )}
                    </td>
                    <td className="px-3.5 py-2 text-right">
                      {c.research_signal ? (
                        <span className="inline-flex items-center gap-1.5">
                          <SignalBadge signal={c.research_signal} compact />
                          <span className="num text-2xs text-muted">{fmtScore(c.research_score)}</span>
                        </span>
                      ) : (
                        <span className="text-2xs text-faint">Not run</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {first?.validation && (
            <p className="border-t border-line px-3.5 py-2 text-2xs text-faint">
              Ranking uses the trailing year (estimate). The earlier-period columns re-run the equal risk contribution
              portfolio with and without each candidate from {fmtDateIST(first.validation.start)} to{" "}
              {fmtDateIST(first.validation.end)}, a period the ranking did not see. Research runs automatically for the
              top three.
            </p>
          )}
        </>
      )}
      {data.replacements.length > 0 && (
        <div className="border-t border-line px-3.5 py-3">
          <div className="mb-1.5 text-2xs tracking-wide text-faint uppercase">
            Possible replacements <Tag kind="estimate" />
          </div>
          <ul className="space-y-1.5">
            {data.replacements.map((r) => (
              <li key={`${r.remove}-${r.add}`} className="text-xs text-muted">
                <span className="font-medium text-fg">
                  {r.remove} → {r.add}
                </span>{" "}
                {r.explanation}
              </li>
            ))}
          </ul>
        </div>
      )}
    </Panel>
  );
}

export function Notes({ data }: { data: PortfolioAnalysis }) {
  return (
    <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
      <Panel title="Limitations">
        <ul className="space-y-1.5 px-3.5 py-3 text-xs leading-relaxed text-muted">
          {data.excluded.map((e) => (
            <li key={e.symbol}>
              <span className="font-medium text-fg">{e.symbol} excluded:</span> {e.reason}
            </li>
          ))}
          {data.limitations.map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
      </Panel>
      <Panel title="Assumptions">
        <ul className="space-y-1.5 px-3.5 py-3 text-xs leading-relaxed text-muted">
          {data.assumptions.map((a) => (
            <li key={a}>{a}</li>
          ))}
        </ul>
      </Panel>
    </div>
  );
}

export function SelectionPanel({ data }: { data: PortfolioAnalysis }) {
  const s = data.selection;
  if (!s) return null;
  const pos = Math.min(100, Math.max(0, s.percentile * 100));
  return (
    <Panel
      title="Selection check"
      meta={`${s.portfolios} random portfolios · ${fmtDateIST(s.start)} to ${fmtDateIST(s.end)}`}
      actions={<Tag kind="measured" />}
    >
      <div className="space-y-3 p-3.5">
        <p className="text-sm text-fg">
          Your {s.size} stocks, equally weighted, returned{" "}
          <span className="num font-medium">{pct(s.your_cagr, 1, true)}</span> a year: better than{" "}
          <span className="num font-medium">{pct(s.percentile, 0)}</span> of random {s.size}-stock portfolios.
        </p>
        <div className="relative h-6">
          <div className="absolute inset-x-0 top-2.5 h-1 rounded-full bg-surface-3" />
          <div
            className="absolute top-2.5 h-1 rounded-full"
            style={{ left: "10%", width: "80%", background: "var(--neutral-bar)" }}
            title={`Middle 80% of random portfolios: ${pct(s.p10_cagr, 1, true)} to ${pct(s.p90_cagr, 1, true)} a year`}
          />
          <div
            className="absolute top-0 h-6 w-0.5 -translate-x-1/2 rounded bg-accent"
            style={{ left: `${pos}%` }}
            title="Your stocks"
          />
        </div>
        <div className="num flex justify-between text-2xs text-faint">
          <span>Worst random</span>
          <span>Median {pct(s.median_cagr, 1, true)}</span>
          <span>Best random</span>
        </div>
        <p className="text-2xs leading-relaxed text-faint">
          {s.note} Universe: {s.universe}.
        </p>
      </div>
    </Panel>
  );
}

/** The technical evidence behind the plan: strategy comparison, correlations, the candidate screen. */
export function Evidence({ data }: { data: PortfolioAnalysis }) {
  const [selected, setSelected] = useState<string | null>(null);
  const strategy =
    data.strategies.find((s) => s.key === selected) ??
    data.strategies.find((s) => s.key === data.reference_strategy) ??
    data.strategies[0];
  return (
    <div className="flex flex-col gap-3">
      {data.strategies.length > 0 && strategy && (
        <>
          <StrategyTable data={data} selected={strategy.key} onSelect={setSelected} />
          <StrategyDetail data={data} strategy={strategy} />
        </>
      )}
      <div className="grid grid-cols-1 gap-3 xl:grid-cols-3">
        <div className="flex flex-col gap-3 xl:col-span-1">
          <CorrelationPanel data={data} />
          <SelectionPanel data={data} />
        </div>
        <div className={data.correlation ? "xl:col-span-2" : "xl:col-span-3"}>
          <CandidatesPanel data={data} />
        </div>
      </div>
      <Notes data={data} />
    </div>
  );
}
