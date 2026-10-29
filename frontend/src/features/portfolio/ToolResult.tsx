import { cx } from "../../components/ui/primitives";
import type { AskAnswer } from "../../lib/types";
import { pct, rupees } from "./format";

type M = Record<string, number | string | null | Record<string, number>>;

const ROWS: { key: string; label: string; fmt: (v: number | null) => string; better: "higher" | "lower" }[] = [
  { key: "volatility", label: "Estimated swings", fmt: (v) => pct(v, 1), better: "lower" },
  {
    key: "diversification_score",
    label: "Diversification",
    fmt: (v) => (v == null ? "—" : `${v}/100`),
    better: "higher",
  },
  { key: "cagr", label: "Past return a year", fmt: (v) => pct(v, 1, true), better: "higher" },
  { key: "after_tax_cagr", label: "After tax", fmt: (v) => pct(v, 1, true), better: "higher" },
  { key: "max_drawdown", label: "Worst fall", fmt: (v) => pct(v, 0), better: "higher" },
  { key: "covid", label: "COVID-19 replay", fmt: (v) => pct(v, 1, true), better: "higher" },
  { key: "yield", label: "Dividend yield", fmt: (v) => pct(v, 1), better: "higher" },
];

function ScenarioResult({ data }: { data: { before: M; after: M } }) {
  const wa = (data.before.weights ?? {}) as Record<string, number>;
  const wb = (data.after.weights ?? {}) as Record<string, number>;
  const symbols = [...new Set([...Object.keys(wa), ...Object.keys(wb)])];
  return (
    <div className="space-y-2">
      <div className="space-y-1">
        {symbols.map((s) => (
          <div key={s} className="grid grid-cols-[72px_1fr_88px] items-center gap-2 text-2xs">
            <span className="font-medium text-fg">{s}</span>
            <div className="relative h-2 rounded-full bg-surface-3">
              <div
                className="absolute inset-y-0 left-0 rounded-full bg-line-strong"
                style={{ width: `${(wa[s] ?? 0) * 100}%` }}
              />
              <div
                className="absolute inset-y-0 left-0 rounded-full bg-accent transition-[width] duration-500"
                style={{ width: `${(wb[s] ?? 0) * 100}%`, opacity: 0.85, height: "50%", top: "25%" }}
              />
            </div>
            <span className="num text-right text-muted">
              {pct(wa[s] ?? 0, 0)} → <span className="text-fg">{pct(wb[s] ?? 0, 0)}</span>
            </span>
          </div>
        ))}
      </div>
      <table className="num w-full text-2xs">
        <tbody className="divide-y divide-line">
          {ROWS.map((r) => {
            const a = data.before[r.key] as number | null;
            const b = data.after[r.key] as number | null;
            const better = a == null || b == null || a === b ? null : r.better === "higher" ? b > a : b < a;
            return (
              <tr key={r.key}>
                <td className="py-1 font-sans text-muted">{r.label}</td>
                <td className="py-1 text-right text-muted">{r.fmt(a)}</td>
                <td
                  className={cx(
                    "py-1 text-right",
                    better == null ? "text-fg" : better ? "text-accent" : "text-caution",
                  )}
                >
                  {r.fmt(b)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="text-[10px] text-faint">Grey: now. Blue: scenario. Past figures use stocks picked today.</p>
    </div>
  );
}

function CompareResult({ data }: { data: { rows: M[]; current: string } }) {
  return (
    <div className="overflow-x-auto">
      <table className="num w-full min-w-[420px] text-2xs">
        <thead>
          <tr className="text-faint">
            <th className="py-1 text-left font-medium">Objective</th>
            <th className="py-1 text-right font-medium">Swings</th>
            <th className="py-1 text-right font-medium">Past/yr</th>
            <th className="py-1 text-right font-medium">Worst</th>
            <th className="py-1 text-right font-medium">Yield</th>
            <th className="py-1 text-right font-medium">Diversified</th>
            <th className="py-1 text-right font-medium">Largest</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {data.rows.map((o) => (
            <tr key={String(o.key)} className={o.key === data.current ? "text-fg" : "text-muted"}>
              <td className="py-1 font-sans">
                {String(o.label)}
                {o.key === data.current && <span className="ml-1 text-accent">· yours</span>}
              </td>
              <td className="py-1 text-right">{pct(o.volatility as number, 1)}</td>
              <td className="py-1 text-right">{pct(o.cagr as number, 1, true)}</td>
              <td className="py-1 text-right">{pct(o.max_drawdown as number, 0)}</td>
              <td className="py-1 text-right">{pct(o.dividend_yield as number, 1)}</td>
              <td className="py-1 text-right">{String(o.diversification_score ?? "—")}</td>
              <td className="py-1 text-right">
                {String(o.top_weight_symbol ?? "")} {pct(o.top_weight as number, 0)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function InvestigateResult({
  data,
}: {
  data: { periods: [string, number | null, number | null, number | null][]; sector_label: string; symbol: string };
}) {
  const all = data.periods.flatMap(([, a, b, c]) => [a, b, c]).filter((v): v is number => v != null);
  const max = Math.max(0.05, ...all.map(Math.abs));
  const bar = (v: number | null, color: string) => (
    <div className="relative h-1.5 w-full">
      <div className="absolute inset-y-0 left-1/2 w-px bg-line-strong" />
      {v != null && (
        <div
          className="absolute inset-y-0 rounded-full"
          style={{
            background: color,
            left: v >= 0 ? "50%" : `${50 - (Math.abs(v) / max) * 50}%`,
            width: `${(Math.abs(v) / max) * 50}%`,
          }}
        />
      )}
    </div>
  );
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-3 text-[10px] text-faint">
        <span className="inline-flex items-center gap-1">
          <span className="h-1.5 w-3 rounded-full bg-accent" />
          {data.symbol}
        </span>
        <span className="inline-flex items-center gap-1">
          <span className="h-1.5 w-3 rounded-full" style={{ background: "var(--series-2)" }} />
          {data.sector_label}
        </span>
        <span className="inline-flex items-center gap-1">
          <span className="h-1.5 w-3 rounded-full" style={{ background: "var(--neutral-bar)" }} />
          NIFTY 50
        </span>
      </div>
      {data.periods.map(([label, st, sec, mkt]) => (
        <div key={label} className="grid grid-cols-[84px_1fr_120px] items-center gap-2 text-2xs">
          <span className="text-muted">{label.replace("over ", "")}</span>
          <div className="space-y-0.5">
            {bar(st, "var(--accent)")}
            {bar(sec, "var(--series-2)")}
            {bar(mkt, "var(--neutral-bar)")}
          </div>
          <span className="num text-right text-muted">
            <span className="text-fg">{pct(st, 1, true)}</span> · {pct(sec, 0, true)} · {pct(mkt, 0, true)}
          </span>
        </div>
      ))}
    </div>
  );
}

function GoalResult({
  data,
}: {
  data: { probability: number; p10: number; p50: number; p90: number; needed: Record<string, number | null> };
}) {
  return (
    <div className="grid grid-cols-2 gap-2 text-2xs sm:grid-cols-4">
      <div>
        <div className="text-faint">Reached in</div>
        <div className="num text-sm font-semibold text-fg">{pct(data.probability, 0)}</div>
        <div className="text-faint">of past paths</div>
      </div>
      <div>
        <div className="text-faint">Weak · middle · strong</div>
        <div className="num text-fg">
          {rupees(data.p10)} · {rupees(data.p50)} · {rupees(data.p90)}
        </div>
      </div>
      {Object.entries(data.needed ?? {}).map(([k, v]) => (
        <div key={k}>
          <div className="text-faint">Monthly for {k} odds</div>
          <div className="num text-fg">{v == null ? "Out of reach" : v === 0 ? "Nothing extra" : rupees(v)}</div>
        </div>
      ))}
    </div>
  );
}

/** The engine's computed result behind a analyst answer. */
export function ToolResult({ answer }: { answer: AskAnswer }) {
  const d = answer.data as never;
  if (!answer.tool || !answer.data) return null;
  return (
    <div className="mt-2 rounded-md border border-line bg-surface p-2.5">
      <div className="mb-1.5 flex items-center gap-2 text-2xs">
        <span className="font-medium text-fg">{answer.title}</span>
        <span className="rounded border border-accent/40 px-1 text-[10px] font-medium text-accent uppercase">
          Computed
        </span>
      </div>
      {answer.tool === "scenario" && <ScenarioResult data={d} />}
      {answer.tool === "compare" && <CompareResult data={d} />}
      {answer.tool === "investigate" && <InvestigateResult data={d} />}
      {answer.tool === "goal" && <GoalResult data={d} />}
    </div>
  );
}
