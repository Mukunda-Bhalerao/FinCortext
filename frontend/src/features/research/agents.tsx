import { useState } from "react";
import { cx } from "../../components/ui/primitives";
import { fmtNumber, fmtStamp } from "../../lib/format";
import type { AgentName, AgentOutput, Composite, Evidence, ResearchItem, Signal } from "../../lib/types";

export const AGENT_ORDER: AgentName[] = ["firm", "industry", "macro", "sentiment"];

export const AGENT_META: Record<AgentName, { title: string; scope: string }> = {
  firm: { title: "Firm", scope: "Valuation, profitability, growth, balance sheet, technicals" },
  industry: { title: "Industry", scope: "Sector momentum, peer rank, breadth, structure" },
  macro: { title: "Macro", scope: "Rates, currency, crude, inflation, sector exposure" },
  sentiment: { title: "Sentiment", scope: "News tone, analyst consensus, event signals" },
};

// Green and red are reserved for price direction; research signals use the accent and caution tones.
const SIGNAL: Record<Signal, { label: string; cls: string }> = {
  positive: { label: "Positive", cls: "border-accent/40 bg-accent-soft text-accent" },
  neutral: { label: "Neutral", cls: "border-line-strong text-muted" },
  negative: { label: "Negative", cls: "border-caution/40 bg-caution-soft text-caution" },
  insufficient_data: { label: "Insufficient data", cls: "border-line text-faint" },
};

export function SignalBadge({ signal, compact }: { signal: Signal; compact?: boolean }) {
  const s = SIGNAL[signal];
  return (
    <span
      className={cx(
        "inline-flex h-5 items-center rounded border px-1.5 text-2xs font-medium whitespace-nowrap",
        s.cls,
      )}
    >
      {compact && signal === "insufficient_data" ? "No data" : s.label}
    </span>
  );
}

export function fmtScore(v: number | null | undefined): string {
  if (v == null) return "—";
  const s = fmtNumber(Math.abs(v), 2);
  return v > 0 ? `+${s}` : v < 0 ? `−${s}` : s;
}

/** Diverging bar for a -1..1 score, centred on zero. */
export function ScoreBar({ score, className }: { score: number | null; className?: string }) {
  const width = score == null ? 0 : Math.min(50, Math.abs(score) * 50);
  return (
    <div className={cx("relative h-1.5 rounded-full bg-surface-3", className)} aria-hidden>
      <span className="absolute top-0 left-1/2 h-full w-px bg-line-strong" />
      {score != null && (
        <span
          className={cx("absolute top-0 h-full rounded-full", score >= 0 ? "bg-accent" : "bg-caution")}
          style={score >= 0 ? { left: "50%", width: `${width}%` } : { right: "50%", width: `${width}%` }}
        />
      )}
    </div>
  );
}

export function SignalCell({ output }: { output: { signal: Signal; score: number | null } | undefined }) {
  if (!output) return <span className="text-2xs text-faint">—</span>;
  return (
    <div className="flex items-center gap-2">
      <SignalBadge signal={output.signal} compact />
      <span className="num text-xs text-muted">{fmtScore(output.score)}</span>
    </div>
  );
}

function fmtEvidenceValue(e: Evidence): string {
  if (e.value == null) return "—";
  if (typeof e.value === "string") return e.value;
  const decimals = e.unit === "count" || Number.isInteger(e.value) ? 0 : 2;
  const n = fmtNumber(e.value, decimals);
  switch (e.unit) {
    case "%":
      return `${n}%`;
    case "x":
      return `${n}x`;
    case "pp":
      return `${e.value > 0 ? "+" : ""}${n} pp`;
    case "INR":
      return `₹${n}`;
    case "USD":
      return `$${n}`;
    default:
      return n;
  }
}

function EvidenceRow({ e }: { e: Evidence }) {
  return (
    <li className="grid grid-cols-[1fr_auto] gap-x-3 gap-y-0.5 py-1.5">
      <span className="min-w-0 text-xs text-muted">{e.metric}</span>
      <span className="num text-right text-xs text-fg">{fmtEvidenceValue(e)}</span>
      <span className="col-span-2 flex flex-wrap gap-x-2 text-2xs text-faint">
        {e.detail && <span>{e.detail}</span>}
        <span>
          {e.source}
          {e.as_of && ` · ${fmtStamp(e.as_of)}`}
        </span>
        {e.score != null && <span className="num">score {fmtScore(e.score)}</span>}
      </span>
    </li>
  );
}

export function AgentCard({ output }: { output: AgentOutput }) {
  const [open, setOpen] = useState(false);
  const meta = AGENT_META[output.agent];
  const groups = [...new Set(output.evidence.map((e) => e.factor))];
  return (
    <section className="flex min-w-0 flex-col rounded-lg border border-line bg-surface">
      <header className="flex items-start gap-2 border-b border-line px-3.5 py-2.5">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold tracking-tight text-fg">{meta.title}</h3>
          <p className="truncate text-2xs text-faint">{meta.scope}</p>
        </div>
        <div className="ml-auto">
          <SignalBadge signal={output.signal} />
        </div>
      </header>
      <div className="space-y-3 px-3.5 py-3">
        <div className="grid grid-cols-3 gap-3">
          <div>
            <div className="text-2xs tracking-wide text-faint uppercase">Score</div>
            <div className="num text-sm text-fg">{fmtScore(output.score)}</div>
          </div>
          <div>
            <div className="text-2xs tracking-wide text-faint uppercase">Confidence</div>
            <div className="num text-sm text-fg">{Math.round(output.confidence * 100)}%</div>
          </div>
          <div>
            <div className="text-2xs tracking-wide text-faint uppercase">Coverage</div>
            <div className="num text-sm text-fg">{Math.round(output.coverage * 100)}%</div>
          </div>
        </div>
        <ScoreBar score={output.score} />
        <ul className="space-y-1">
          {output.factors
            .filter((f) => f.weight > 0 || f.note)
            .map((f) => (
              <li key={f.name} className="grid grid-cols-[1fr_64px_44px] items-center gap-2 text-xs">
                <span className={cx("truncate", f.score == null ? "text-faint" : "text-muted")} title={f.note ?? undefined}>
                  {f.name}
                  {f.weight > 0 && <span className="text-faint"> · {Math.round(f.weight * 100)}%</span>}
                </span>
                <ScoreBar score={f.score} />
                <span className="num text-right text-faint">{f.score == null ? (f.note ? "n/s" : "—") : fmtScore(f.score)}</span>
              </li>
            ))}
        </ul>
        {output.rationale && <p className="text-xs leading-relaxed text-muted">{output.rationale}</p>}
        {output.data_gaps.length > 0 && (
          <ul className="space-y-0.5 border-t border-line pt-2">
            {output.data_gaps.map((g) => (
              <li key={g} className="text-2xs leading-relaxed text-faint">
                Gap: {g}
              </li>
            ))}
          </ul>
        )}
        <button
          onClick={() => setOpen((o) => !o)}
          className="text-2xs font-medium text-accent hover:underline"
          aria-expanded={open}
        >
          {open ? "Hide evidence" : `Show evidence (${output.evidence.length})`}
        </button>
        {open && (
          <div className="space-y-2">
            {groups.map((g) => (
              <div key={g}>
                <div className="text-2xs font-semibold tracking-wide text-faint uppercase">{g}</div>
                <ul className="divide-y divide-line">
                  {output.evidence
                    .filter((e) => e.factor === g)
                    .map((e) => (
                      <EvidenceRow key={`${e.factor}-${e.metric}`} e={e} />
                    ))}
                </ul>
              </div>
            ))}
            <p className="text-2xs text-faint">
              Method {output.method} · {output.rationale_source === "model" ? "summary phrased by local model" : "templated summary"} ·
              computed {fmtStamp(output.computed_at)}
            </p>
          </div>
        )}
      </div>
    </section>
  );
}

export function CompositeSummary({ composite }: { composite: Composite }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
      <SignalBadge signal={composite.signal} />
      <span className="num text-sm text-fg">{fmtScore(composite.score)}</span>
      <ScoreBar score={composite.score} className="w-32" />
      <span className="text-2xs text-faint">
        {composite.agents_used} of 4 agents · confidence {Math.round(composite.confidence * 100)}%
      </span>
    </div>
  );
}

export function StateLabel({ item }: { item: ResearchItem }) {
  if (item.state === "queued") return <span className="text-2xs text-muted">Queued</span>;
  if (item.state === "running") return <span className="text-2xs text-accent">Running</span>;
  if (item.state === "failed") return <span className="text-2xs text-caution" title={item.error ?? undefined}>Failed</span>;
  if (!item.report) return <span className="text-2xs text-faint">Not run</span>;
  return (
    <span className={cx("text-2xs", item.stale ? "text-caution" : "text-faint")} title={item.stale ? "Refresh pending" : undefined}>
      {fmtStamp(item.report.computed_at)}
    </span>
  );
}

export const isBusy = (item: ResearchItem | undefined) => item?.state === "queued" || item?.state === "running";
