import { useState } from "react";
import { cx } from "../../components/ui/primitives";
import { fmtDateIST, fmtStamp } from "../../lib/format";
import type { Brief, Fact, FactBasis, Insight, InsightAction } from "../../lib/types";

export const BASIS_LABEL: Record<FactBasis, string> = {
  measured: "Measured",
  estimate: "Estimate",
  observed: "Observed",
  replay: "Replay",
};

const BASIS_HINT: Record<FactBasis, string> = {
  measured: "Computed from a backtest on historical prices and dividends",
  estimate: "From the trailing-year risk model; describes the present, not the future",
  observed: "A stored reading from the research agents",
  replay: "Today's weights run through a past episode on real prices",
};

export function BasisTag({ basis }: { basis: FactBasis }) {
  return (
    <span
      title={BASIS_HINT[basis]}
      className={cx(
        "shrink-0 rounded border px-1 text-[10px] font-medium tracking-wide uppercase",
        basis === "measured" || basis === "replay" ? "border-accent/40 text-accent" : "border-line-strong text-faint",
      )}
    >
      {BASIS_LABEL[basis]}
    </span>
  );
}

export function FactList({ facts }: { facts: Fact[] }) {
  return (
    <ul className="space-y-1.5">
      {facts.map((f) => (
        <li key={f.id} className="flex gap-2 text-2xs leading-relaxed">
          <BasisTag basis={f.basis} />
          <span className="min-w-0 text-muted">
            {f.text}
            <span className="block text-faint">
              {f.source}
              {f.as_of && ` · ${fmtDateIST(f.as_of)}`}
            </span>
          </span>
        </li>
      ))}
    </ul>
  );
}

const SEVERITY = {
  high: { dot: "bg-down", label: "Important" },
  medium: { dot: "bg-caution", label: "Worth a look" },
  low: { dot: "bg-faint", label: "Note" },
};

const KIND_LABEL = {
  risk: "Risk",
  opportunity: "Option",
  change: "What changed",
  performance: "Track record",
  data: "Data",
};

export function InsightCard({
  insight,
  facts,
  onAction,
  delay = 0,
}: {
  insight: Insight;
  facts: Map<string, Fact>;
  onAction?: (a: InsightAction) => void;
  delay?: number;
}) {
  const [open, setOpen] = useState(false);
  const cited = insight.facts.map((id) => facts.get(id)).filter((f): f is Fact => !!f);
  const sev = SEVERITY[insight.severity];
  return (
    <article
      className="fc-rise flex min-w-0 flex-col rounded-lg border border-line bg-surface p-3"
      style={{ animationDelay: `${delay}ms` }}
    >
      <div className="flex items-center gap-1.5 text-2xs text-faint">
        <span className={cx("h-1.5 w-1.5 rounded-full", sev.dot)} aria-hidden />
        <span>{KIND_LABEL[insight.kind]}</span>
        <span className="sr-only">, {sev.label}</span>
      </div>
      <h3 className="mt-1 text-sm font-semibold text-fg">{insight.title}</h3>
      <p className="mt-1 text-xs leading-relaxed text-muted">{insight.body}</p>
      <div className="mt-auto flex flex-wrap items-center gap-2 pt-2.5">
        {insight.action && onAction && (
          <button
            onClick={() => onAction(insight.action!)}
            className="rounded-md border border-accent/50 px-2 py-0.5 text-2xs font-medium text-accent hover:bg-accent-soft"
          >
            {insight.action.label}
          </button>
        )}
        {cited.length > 0 && (
          <button onClick={() => setOpen((v) => !v)} aria-expanded={open} className="text-2xs text-faint hover:text-fg">
            {open ? "Hide evidence" : `Evidence (${cited.length})`}
          </button>
        )}
      </div>
      {open && (
        <div className="mt-2 border-t border-line pt-2">
          <FactList facts={cited} />
        </div>
      )}
    </article>
  );
}

export function BriefHero({
  brief,
  onAction,
  limit = 6,
}: {
  brief: Brief;
  onAction?: (a: InsightAction) => void;
  limit?: number;
}) {
  const facts = new Map(brief.facts.map((f) => [f.id, f]));
  const [all, setAll] = useState(false);
  const shown = all ? brief.insights : brief.insights.slice(0, limit);
  const [showSources, setShowSources] = useState(false);
  const narrativeFacts = (brief.narrative?.cited ?? []).map((id) => facts.get(id)).filter((f): f is Fact => !!f);
  return (
    <section className="flex flex-col gap-3">
      <div className="rounded-lg border border-line bg-surface p-4">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-2xs text-faint">
          <span className="font-medium tracking-wide text-accent uppercase">Your brief</span>
          {brief.analysis_at && <span>Analysis {fmtStamp(brief.analysis_at)}</span>}
        </div>
        <p className="mt-1.5 text-base leading-snug font-semibold text-fg sm:text-lg">{brief.headline}</p>
        {brief.narrative && (
          <div className="mt-2.5">
            <p className="max-w-4xl text-sm leading-relaxed text-muted">{brief.narrative.text}</p>
            <div className="mt-1.5 flex flex-wrap items-center gap-2 text-2xs text-faint">
              <span title="Written by a language model from the facts below; numbers not found in those facts are rejected">
                Written by {brief.narrative.model} from {narrativeFacts.length} checked facts
              </span>
              {narrativeFacts.length > 0 && (
                <button onClick={() => setShowSources((v) => !v)} className="hover:text-fg" aria-expanded={showSources}>
                  {showSources ? "Hide sources" : "Show sources"}
                </button>
              )}
            </div>
            {showSources && (
              <div className="mt-2 border-t border-line pt-2">
                <FactList facts={narrativeFacts} />
              </div>
            )}
          </div>
        )}
      </div>
      {shown.length > 0 && (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {shown.map((i, k) => (
            <InsightCard key={i.id} insight={i} facts={facts} onAction={onAction} delay={k * 40} />
          ))}
        </div>
      )}
      {brief.insights.length > limit && (
        <button onClick={() => setAll((v) => !v)} className="self-start text-xs text-muted hover:text-fg">
          {all ? "Show fewer" : `Show all ${brief.insights.length} insights`}
        </button>
      )}
    </section>
  );
}
