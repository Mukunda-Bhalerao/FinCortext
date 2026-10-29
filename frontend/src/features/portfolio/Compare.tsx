import { cx, Panel } from "../../components/ui/primitives";
import type { PortfolioPlan } from "../../lib/types";
import { pct, rupees } from "./format";

interface Metric {
  label: string;
  get: (p: PortfolioPlan) => number | null | undefined;
  fmt: (v: number | null | undefined) => string;
  better: "higher" | "lower";
  hint?: string;
}

const METRICS: Metric[] = [
  { label: "Estimated yearly swings", get: (p) => p.risk?.volatility, fmt: (v) => pct(v, 1), better: "lower" },
  {
    label: "Diversification score",
    get: (p) => p.risk?.diversification_score,
    fmt: (v) => (v == null ? "—" : `${v}/100`),
    better: "higher",
  },
  { label: "Largest single weight", get: (p) => p.risk?.largest_weight, fmt: (v) => pct(v, 0), better: "lower" },
  {
    label: "Past return a year (before tax)",
    get: (p) => p.backtest?.pre_tax.cagr,
    fmt: (v) => pct(v, 1, true),
    better: "higher",
    hint: "Measured, with stocks picked today",
  },
  {
    label: "Past return a year (after tax)",
    get: (p) => p.backtest?.after_tax?.cagr,
    fmt: (v) => pct(v, 1, true),
    better: "higher",
  },
  { label: "Worst fall", get: (p) => p.backtest?.pre_tax.max_drawdown, fmt: (v) => pct(v, 0), better: "higher" },
  {
    label: "COVID-19 crash replay",
    get: (p) => p.stress.find((s) => s.key === "covid_2020")?.portfolio,
    fmt: (v) => pct(v, 1, true),
    better: "higher",
  },
  { label: "Costs a year", get: (p) => p.backtest?.costs_per_year, fmt: (v) => pct(v, 2), better: "lower" },
  { label: "Estimated charges to set up", get: (p) => p.trades?.est_costs, fmt: rupees, better: "lower" },
];

function describe(p: PortfolioPlan): string {
  return `${p.objective.label}: ${p.assets.map((a) => `${a.symbol} ${pct(a.weight, 0)}`).join(", ")}`;
}

/** Side-by-side view of a pinned scenario and the current one, with the better side marked. */
export function ScenarioCompare({
  pinned,
  current,
  onClear,
}: {
  pinned: PortfolioPlan;
  current: PortfolioPlan;
  onClear: () => void;
}) {
  return (
    <Panel
      title="Compare scenarios"
      meta="Estimates describe today; past figures are measured"
      actions={
        <button onClick={onClear} className="text-2xs text-muted hover:text-fg">
          Clear
        </button>
      }
    >
      <div className="overflow-x-auto">
        <table className="w-full min-w-[520px] text-left text-sm">
          <thead>
            <tr className="border-b border-line text-2xs tracking-wide text-faint uppercase">
              <th className="px-3.5 py-1.5 font-medium" />
              <th className="px-3 py-1.5 font-medium">Pinned (A)</th>
              <th className="px-3.5 py-1.5 font-medium">Current (B)</th>
            </tr>
            <tr className="border-b border-line text-2xs text-muted">
              <td className="px-3.5 py-1.5" />
              <td className="max-w-64 px-3 py-1.5">{describe(pinned)}</td>
              <td className="max-w-64 px-3.5 py-1.5">{describe(current)}</td>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {METRICS.map((m) => {
              const a = m.get(pinned);
              const b = m.get(current);
              const win =
                a == null || b == null || a === b ? null : (m.better === "higher" ? b > a : b < a) ? "b" : "a";
              return (
                <tr key={m.label}>
                  <td className="px-3.5 py-1.5 text-xs text-muted" title={m.hint}>
                    {m.label}
                  </td>
                  <td className={cx("num px-3 py-1.5", win === "a" ? "font-semibold text-fg" : "text-muted")}>
                    {m.fmt(a)}
                  </td>
                  <td className={cx("num px-3.5 py-1.5", win === "b" ? "font-semibold text-fg" : "text-muted")}>
                    {m.fmt(b)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="border-t border-line px-3.5 py-2 text-2xs text-faint">
        Bold marks the better side on each line. Past returns here are flattered by hindsight, so weigh the risk lines
        as much as the return lines.
      </p>
    </Panel>
  );
}
