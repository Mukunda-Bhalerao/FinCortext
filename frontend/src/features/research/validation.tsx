import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { cx, ErrorState, Panel, Skeleton } from "../../components/ui/primitives";
import { api } from "../../lib/api";
import { fmtDateIST, fmtStamp } from "../../lib/format";
import type { SignalTest, ValidationStatus, Verdict } from "../../lib/types";

export const VERDICT: Record<Verdict, { label: string; cls: string; hint: string }> = {
  evidence: {
    label: "Shown value",
    cls: "border-accent/50 text-accent",
    hint: "Passed every pre-set test: higher scores came before better returns, consistently.",
  },
  negative: {
    label: "Pointed the wrong way",
    cls: "border-caution/50 text-caution",
    hint: "Higher scores came before worse returns, consistently.",
  },
  inconclusive: {
    label: "Unproven",
    cls: "border-line-strong text-muted",
    hint: "No reliable link with later returns. Treat the score as organised evidence, not a forecast.",
  },
  insufficient: {
    label: "Not enough history",
    cls: "border-line-strong text-faint",
    hint: "Too few months to judge either way.",
  },
};

export function VerdictBadge({ verdict }: { verdict: Verdict }) {
  const v = VERDICT[verdict];
  return (
    <span
      title={v.hint}
      className={cx("rounded border px-1.5 py-px text-[10px] font-medium tracking-wide uppercase", v.cls)}
    >
      {v.label}
    </span>
  );
}

const busy = (s: ValidationStatus | undefined) => s?.state === "queued" || s?.state === "running";

export function useValidation() {
  return useQuery({
    queryKey: ["validation"],
    queryFn: api.validation,
    refetchInterval: (q) => (busy(q.state.data) ? 4_000 : 300_000),
  });
}

const n3 = (v: number | null | undefined) =>
  v == null ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(3)}`;
const p1 = (v: number | null | undefined) =>
  v == null ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v * 100).toFixed(1)}%`;

/** IC with its 90% interval on a fixed -0.15..+0.15 scale; zero marked. */
function ICBar({ t }: { t: SignalTest }) {
  const span = 0.15;
  const x = (v: number) => `${((Math.max(-span, Math.min(span, v)) + span) / (2 * span)) * 100}%`;
  if (t.mean_ic == null) return <span className="text-2xs text-faint">—</span>;
  return (
    <div
      className="relative h-4 w-full min-w-28"
      title={`Average ${n3(t.mean_ic)}, 90% interval ${n3(t.ic_low)} to ${n3(t.ic_high)}`}
    >
      <div className="absolute inset-x-0 top-2 h-px bg-line" />
      <div className="absolute top-0.5 h-3 w-px bg-line-strong" style={{ left: "50%" }} />
      {t.ic_low != null && t.ic_high != null && (
        <div
          className="absolute top-1.5 h-1 rounded-full bg-accent/30"
          style={{ left: x(t.ic_low), width: `calc(${x(t.ic_high)} - ${x(t.ic_low)})` }}
        />
      )}
      <div
        className="absolute top-0.5 h-3 w-1.5 -translate-x-1/2 rounded-sm bg-accent"
        style={{ left: x(t.mean_ic) }}
      />
    </div>
  );
}

function Row({ t }: { t: SignalTest }) {
  return (
    <tr className={t.kind === "factor" ? "text-xs" : undefined}>
      <td className={cx("py-2 pr-3", t.kind === "factor" ? "pl-7" : "pl-3.5")}>
        <div className={cx(t.kind === "factor" ? "text-muted" : "font-medium text-fg")}>{t.label}</div>
        {t.inputs && <div className="max-w-72 text-2xs text-faint">{t.inputs}</div>}
      </td>
      <td className="px-3 py-2">
        <VerdictBadge verdict={t.verdict} />
      </td>
      <td className="num px-3 py-2 text-right text-fg">{n3(t.mean_ic)}</td>
      <td className="w-36 px-3 py-2">
        <ICBar t={t} />
      </td>
      <td className="num px-3 py-2 text-right text-muted">
        {n3(t.first_half_ic)} / {n3(t.second_half_ic)}
      </td>
      <td className="num px-3 py-2 text-right text-muted" title="Top fifth by score minus the universe, after costs">
        {p1(t.spread_annual)}
      </td>
      <td className="num px-3.5 py-2 text-right text-faint">
        {t.months}
        {t.kind !== "factor" && t.agent !== "macro" ? ` · ${t.avg_stocks.toFixed(0)}` : ""}
      </td>
    </tr>
  );
}

/** Did the agents' scores line up with what happened next? Replay plus forward tracking. */
export function ValidationPanel() {
  const qc = useQueryClient();
  const q = useValidation();
  const [factors, setFactors] = useState(false);
  const r = q.data?.result;
  const run = async () => {
    await api.runValidation();
    await qc.invalidateQueries({ queryKey: ["validation"] });
  };
  const main = r?.tests.filter((t) => t.kind !== "factor") ?? [];
  const parts = r?.tests.filter((t) => t.kind === "factor") ?? [];
  return (
    <Panel
      title="Track record"
      meta={
        busy(q.data)
          ? (q.data?.progress ?? "Replaying the agents…")
          : r
            ? `${r.universe} · ${fmtDateIST(r.start)} to ${fmtDateIST(r.end)} · checked ${fmtStamp(r.computed_at)}`
            : undefined
      }
      actions={
        <button
          onClick={() => void run()}
          disabled={busy(q.data)}
          className="rounded-md border border-line px-2 py-0.5 text-2xs text-muted hover:border-line-strong hover:text-fg disabled:opacity-50"
        >
          {busy(q.data) ? "Running…" : "Run again"}
        </button>
      }
    >
      {q.isPending ? (
        <Skeleton className="m-3.5 h-32" />
      ) : q.isError ? (
        <ErrorState error={q.error} compact />
      ) : !r ? (
        <p className="p-3.5 text-sm text-muted">
          {busy(q.data)
            ? "Rebuilding each month's research from the data available at the time. This takes about a minute."
            : (q.data?.error ?? "No validation run yet.")}
        </p>
      ) : (
        <div>
          <div className="space-y-1.5 border-b border-line px-3.5 py-3">
            <p className="text-sm font-semibold text-fg">{r.headline}</p>
            <p className="max-w-4xl text-xs leading-relaxed text-muted">
              Each month since {fmtDateIST(r.start)}, the agents were re-run on {r.stocks} stocks using only data
              available that day, and their scores were compared with the next {r.horizon_sessions} sessions' returns. A
              score that helps would show a positive average and an interval clear of zero, in both halves of the
              history.
            </p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[860px] text-left text-sm">
              <thead>
                <tr className="border-b border-line text-2xs tracking-wide text-faint uppercase">
                  <th className="py-1.5 pr-3 pl-3.5 font-medium">Signal</th>
                  <th className="px-3 py-1.5 font-medium">Verdict</th>
                  <th
                    className="px-3 py-1.5 text-right font-medium"
                    title="Average rank correlation with next month's returns"
                  >
                    Avg IC
                  </th>
                  <th className="px-3 py-1.5 font-medium">IC and 90% range</th>
                  <th className="px-3 py-1.5 text-right font-medium">1st / 2nd half</th>
                  <th className="px-3 py-1.5 text-right font-medium">Top fifth vs all</th>
                  <th className="px-3.5 py-1.5 text-right font-medium">Months · stocks</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {main.map((t) => (
                  <Row key={t.key} t={t} />
                ))}
                {factors && parts.map((t) => <Row key={t.key} t={t} />)}
              </tbody>
            </table>
          </div>
          <div className="flex flex-wrap items-center gap-3 border-t border-line px-3.5 py-2">
            <button onClick={() => setFactors((v) => !v)} className="text-2xs text-muted hover:text-fg">
              {factors ? "Hide factor detail" : `Show ${parts.length} individual factors`}
            </button>
          </div>
          <div className="grid grid-cols-1 gap-4 border-t border-line p-3.5 text-xs md:grid-cols-2">
            <div>
              <div className="mb-1 text-2xs tracking-wide text-faint uppercase">Cannot be replayed</div>
              <ul className="space-y-1 text-muted">
                {r.untestable.map((u) => (
                  <li key={u.component}>
                    <span className="font-medium text-fg">{u.component}</span>: {u.reason}
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <div className="mb-1 text-2xs tracking-wide text-faint uppercase">Forward test (out of sample)</div>
              <p className="text-muted">
                Each weekly run records the agents' scores for the whole universe before the outcome exists.{" "}
                {r.tracking.recorded_snapshots
                  ? `${r.tracking.recorded_snapshots} snapshot${r.tracking.recorded_snapshots === 1 ? "" : "s"} recorded since ${fmtDateIST(r.tracking.first_recorded)}; ${r.tracking.scored_snapshots} have a known outcome so far (snapshots at least four weeks apart count).`
                  : "Recording starts with this run."}
              </p>
              {r.tracking.recorded?.some((x) => x.snapshots > 0) && (
                <ul className="num mt-1 space-y-0.5 text-2xs">
                  {r.tracking.recorded.map((x) => (
                    <li key={x.key} className="flex items-center gap-2">
                      <span className="text-muted">{x.label}</span>
                      <span className="text-fg">{n3(x.mean_ic)}</span>
                      <VerdictBadge verdict={x.verdict} />
                    </li>
                  ))}
                </ul>
              )}
              <p className="mt-2 text-muted">Live reports (incl. news sentiment): {r.tracking.status}</p>
              {r.tracking.pooled_ic != null && (
                <p className="num mt-1 text-fg">Pooled IC so far {n3(r.tracking.pooled_ic)}</p>
              )}
            </div>
          </div>
          <details className="border-t border-line px-3.5 py-2.5 text-xs text-muted">
            <summary className="cursor-pointer text-2xs font-medium tracking-wide text-faint uppercase">
              Method and limitations
            </summary>
            <ul className="mt-2 list-disc space-y-1 pl-4 leading-relaxed">
              {[...r.method, ...r.limitations].map((m) => (
                <li key={m}>{m}</li>
              ))}
            </ul>
          </details>
        </div>
      )}
    </Panel>
  );
}
