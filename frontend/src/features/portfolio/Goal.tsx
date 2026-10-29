import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { ErrorState, Panel } from "../../components/ui/primitives";
import { api } from "../../lib/api";
import { fmtDateIST } from "../../lib/format";
import type { GoalProjection, Preferences } from "../../lib/types";
import { pct, rupees } from "./format";

/** p10-p90 band, median line, target and money put in, by year. */
function Fan({ g }: { g: GoalProjection }) {
  const W = 520;
  const H = 180;
  const pad = { l: 8, r: 8, t: 10, b: 20 };
  const max = Math.max(g.target, ...g.path.map((p) => p.p90)) * 1.05;
  const x = (i: number) => pad.l + (i / g.years) * (W - pad.l - pad.r);
  const y = (v: number) => pad.t + (1 - v / max) * (H - pad.t - pad.b);
  const pts = [{ year: 0, p10: g.initial, p50: g.initial, p90: g.initial, invested: g.initial }, ...g.path];
  const band =
    pts.map((p, i) => `${i ? "L" : "M"}${x(p.year)},${y(p.p90)}`).join(" ") +
    " " +
    [...pts]
      .reverse()
      .map((p) => `L${x(p.year)},${y(p.p10)}`)
      .join(" ") +
    " Z";
  const line = (k: "p50" | "invested") => pts.map((p, i) => `${i ? "L" : "M"}${x(p.year)},${y(p[k])}`).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-44 w-full" role="img" aria-label="Range of outcomes by year">
      <path d={band} fill="var(--accent)" opacity="0.14" />
      <path d={line("invested")} fill="none" stroke="var(--text-faint)" strokeWidth="1.5" strokeDasharray="4 3" />
      <path d={line("p50")} fill="none" stroke="var(--accent)" strokeWidth="2" />
      <line x1={pad.l} x2={W - pad.r} y1={y(g.target)} y2={y(g.target)} stroke="var(--caution)" strokeWidth="1.5" />
      <text x={W - pad.r} y={y(g.target) - 4} textAnchor="end" fontSize="10" fill="var(--caution)">
        Target {rupees(g.target)}
      </text>
      {pts
        .filter((p) => p.year % Math.max(1, Math.round(g.years / 5)) === 0)
        .map((p) => (
          <text key={p.year} x={x(p.year)} y={H - 4} textAnchor="middle" fontSize="10" fill="var(--text-faint)">
            {p.year === 0 ? "Now" : `${p.year}y`}
          </text>
        ))}
      {g.path.map((p) => (
        <rect key={p.year} x={x(p.year) - 8} y={0} width={16} height={H} fill="transparent">
          <title>{`Year ${p.year}: middle ${rupees(p.p50)}, range ${rupees(p.p10)} to ${rupees(p.p90)}, put in ${rupees(p.invested)}`}</title>
        </rect>
      ))}
    </svg>
  );
}

export function GoalPlanner({ prefs }: { prefs: Preferences }) {
  const [target, setTarget] = useState(5_000_000);
  const [years, setYears] = useState(10);
  const [monthly, setMonthly] = useState(10_000);
  const goal = useMutation({
    mutationFn: () => api.goal({ preferences: prefs, target, years, initial: prefs.capital, monthly }),
  });
  const g = goal.data;
  const field =
    "num mt-1 h-8 w-full rounded-md border border-line bg-surface-2 px-2 text-sm text-fg outline-none focus:border-accent";
  return (
    <Panel
      title="Goal planning"
      meta="A range from this plan's own history, not a forecast"
      actions={
        <span className="rounded border border-line-strong px-1 text-[10px] font-medium tracking-wide text-faint uppercase">
          Hypothesis
        </span>
      }
    >
      <form
        className="grid grid-cols-2 gap-3 border-b border-line p-3.5 sm:grid-cols-4"
        onSubmit={(e) => {
          e.preventDefault();
          goal.mutate();
        }}
      >
        <label className="text-2xs text-faint">
          Target amount (₹)
          <input
            type="number"
            min={10000}
            step="any"
            value={target}
            onChange={(e) => setTarget(Number(e.target.value))}
            className={field}
          />
        </label>
        <label className="text-2xs text-faint">
          In how many years
          <input
            type="number"
            min={1}
            max={30}
            value={years}
            onChange={(e) => setYears(Number(e.target.value))}
            className={field}
          />
        </label>
        <label className="text-2xs text-faint">
          Added every month (₹)
          <input
            type="number"
            min={0}
            step="any"
            value={monthly}
            onChange={(e) => setMonthly(Number(e.target.value))}
            className={field}
          />
        </label>
        <div className="flex items-end">
          <button
            type="submit"
            disabled={goal.isPending || target <= 0 || years < 1}
            className="h-8 w-full rounded-md bg-accent px-3 text-xs font-medium text-white disabled:opacity-50"
          >
            {goal.isPending ? "Working it out…" : g ? "Recalculate" : "See the range"}
          </button>
        </div>
        <p className="col-span-full text-2xs text-faint">
          Starts from {rupees(prefs.capital)} (the amount above) in the {prefs.objective.replace("_", " ")} plan.
        </p>
      </form>
      {goal.isError ? (
        <ErrorState error={goal.error} compact />
      ) : g ? (
        <div className="grid grid-cols-1 gap-4 p-3.5 lg:grid-cols-5">
          <div className="space-y-2 lg:col-span-2">
            <p className="text-sm leading-relaxed text-fg">
              In <span className="num font-semibold">{pct(g.probability, 0)}</span> of resampled histories this plan
              reached {rupees(g.target)} in {g.years} years, putting in {rupees(g.invested)} in total.
            </p>
            <dl className="num grid grid-cols-3 gap-2 text-xs">
              <div>
                <dt className="text-faint">Weak case</dt>
                <dd className="text-fg">{rupees(g.p10)}</dd>
              </div>
              <div>
                <dt className="text-faint">Middle</dt>
                <dd className="text-fg">{rupees(g.p50)}</dd>
              </div>
              <div>
                <dt className="text-faint">Strong case</dt>
                <dd className="text-fg">{rupees(g.p90)}</dd>
              </div>
            </dl>
            {g.benchmark_probability != null && (
              <p className="text-xs text-muted">
                The same calculation on the NIFTY 50 reaches the target in {pct(g.benchmark_probability, 0)} of
                histories (middle {rupees(g.benchmark_p50)}).
              </p>
            )}
            <ul className="space-y-1 text-2xs leading-relaxed text-faint">
              {g.caveats.map((c) => (
                <li key={c}>{c}</li>
              ))}
              <li>
                {g.method} History {fmtDateIST(g.history_from)} to {fmtDateIST(g.history_to)}.
              </li>
            </ul>
          </div>
          <div className="min-w-0 lg:col-span-3">
            <div className="mb-1 flex flex-wrap gap-3 text-2xs text-muted">
              <span className="inline-flex items-center gap-1.5">
                <span className="h-0 w-4 border-t-2 border-accent" /> Middle outcome
              </span>
              <span className="inline-flex items-center gap-1.5">
                <span className="h-2 w-4 rounded-sm bg-accent/20" /> Weak to strong case
              </span>
              <span className="inline-flex items-center gap-1.5">
                <span className="h-0 w-4 border-t-2 border-dashed border-faint" /> Money put in
              </span>
            </div>
            <Fan g={g} />
          </div>
        </div>
      ) : (
        <p className="p-3.5 text-xs text-muted">
          Set a target and a date to see how often this plan's past behaviour would have got there, and how wide the
          range is.
        </p>
      )}
    </Panel>
  );
}
