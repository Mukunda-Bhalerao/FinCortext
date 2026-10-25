import { useQuery } from "@tanstack/react-query";
import { cx, Panel } from "../../components/ui/primitives";
import { api } from "../../lib/api";
import { fmtDateTimeIST, fmtStamp } from "../../lib/format";
import type { HistoryPoint, ResearchChanges } from "../../lib/types";

/** Composite score over stored reports, -1..+1 with the zero line. */
function Sparkline({ points }: { points: HistoryPoint[] }) {
  const scored = points.filter((p) => p.score != null);
  const W = 240;
  const H = 56;
  if (scored.length < 2) return null;
  const t0 = new Date(scored[0]!.computed_at).getTime();
  const t1 = new Date(scored.at(-1)!.computed_at).getTime();
  const x = (p: HistoryPoint) =>
    t1 > t0 ? ((new Date(p.computed_at).getTime() - t0) / (t1 - t0)) * (W - 8) + 4 : W / 2;
  const y = (v: number) => H / 2 - (v * (H - 8)) / 2;
  const d = scored.map((p, i) => `${i ? "L" : "M"}${x(p).toFixed(1)},${y(p.score!).toFixed(1)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-14 w-full max-w-60" role="img" aria-label="Composite score history">
      <line x1="0" x2={W} y1={H / 2} y2={H / 2} stroke="var(--border-strong)" strokeDasharray="3 3" />
      <path d={d} fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinejoin="round" />
      {scored.map((p) => (
        <circle
          key={p.computed_at}
          cx={x(p)}
          cy={y(p.score!)}
          r="4"
          fill="var(--accent)"
          stroke="var(--surface)"
          strokeWidth="2"
        >
          <title>{`${fmtDateTimeIST(p.computed_at)}: ${p.score! > 0 ? "+" : ""}${p.score!.toFixed(2)} (${p.signal})`}</title>
        </circle>
      ))}
    </svg>
  );
}

const DIR = { better: "text-accent", worse: "text-caution", neutral: "text-faint" };
const ARROW = { better: "↑", worse: "↓", neutral: "•" };

export function ChangeList({ changes }: { changes: ResearchChanges }) {
  return (
    <ul className="space-y-1">
      {changes.items.map((c, i) => (
        <li key={i} className="flex gap-2 text-xs text-muted">
          <span className={cx("w-3 shrink-0 text-center", DIR[c.direction])} aria-label={c.direction}>
            {ARROW[c.direction]}
          </span>
          <span className="min-w-0">{c.text}</span>
        </li>
      ))}
    </ul>
  );
}

/** Point-in-time research record for one stock: score trend and what changed. */
export function ResearchTimeline({ symbol }: { symbol: string }) {
  const q = useQuery({
    queryKey: ["research-history", symbol],
    queryFn: () => api.researchHistory(symbol),
    staleTime: 60_000,
  });
  const h = q.data;
  if (!h || h.points.length === 0) return null;
  return (
    <Panel
      title="What changed"
      meta={h.changes ? `Since ${fmtStamp(h.changes.since)}` : `Recording since ${fmtStamp(h.first_recorded)}`}
    >
      <div className="grid grid-cols-1 gap-4 p-3.5 md:grid-cols-[auto_1fr]">
        <div>
          <div className="text-2xs tracking-wide text-faint uppercase">Composite over time</div>
          {h.points.length >= 2 ? (
            <Sparkline points={h.points} />
          ) : (
            <p className="mt-1 max-w-60 text-2xs text-faint">
              One stored report so far; the trend appears after the next run.
            </p>
          )}
          <div className="text-2xs text-faint">
            {h.points.length} stored report{h.points.length === 1 ? "" : "s"}
          </div>
        </div>
        <div className="min-w-0">
          {h.changes ? (
            h.changes.items.length ? (
              <ChangeList changes={h.changes} />
            ) : (
              <p className="text-xs text-muted">No material change since {fmtStamp(h.changes.since)}.</p>
            )
          ) : (
            <p className="text-xs text-muted">
              Every run is kept, so later reports will show what moved and why. Older days keep their last run.
            </p>
          )}
        </div>
      </div>
    </Panel>
  );
}
