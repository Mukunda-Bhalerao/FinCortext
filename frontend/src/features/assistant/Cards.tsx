import { Link } from "react-router-dom";
import { IconExternal } from "../../components/ui/icons";
import { cx } from "../../components/ui/primitives";
import { Sparkline } from "../../components/ui/visual";
import type { ChatCard } from "../../lib/types";
import { pct } from "../portfolio/format";

function Change({ v }: { v: number }) {
  return (
    <span className={cx("num text-xs font-medium", v > 0 ? "text-up" : v < 0 ? "text-down" : "text-muted")}>
      {pct(v, 1, true)}
    </span>
  );
}

function RowLine({ r }: { r: ChatCard["rows"][number] }) {
  const body = (
    <>
      <div className="min-w-0 flex-1">
        <div className="truncate text-xs text-fg">{r.label}</div>
        {r.sub && <div className="truncate text-2xs text-faint">{r.sub}</div>}
      </div>
      {r.value && <span className="num shrink-0 text-xs text-fg">{r.value}</span>}
      {r.change != null && <Change v={r.change} />}
      {r.href && <IconExternal className="h-3 w-3 shrink-0 text-faint" />}
    </>
  );
  const cls = "flex items-center gap-2 px-3 py-1.5 hover:bg-surface-2";
  if (r.href)
    return (
      <a href={r.href} target="_blank" rel="noopener noreferrer" className={cls}>
        {body}
      </a>
    );
  if (r.to)
    return (
      <Link to={r.to} className={cls}>
        {body}
      </Link>
    );
  return <div className={cls}>{body}</div>;
}

/** One card of an assistant answer. Every figure in it came from the engine. */
export function AnswerCard({ card }: { card: ChatCard }) {
  return (
    <section className="overflow-hidden rounded-lg border border-line bg-surface-2/50">
      <header className="flex flex-wrap items-baseline gap-x-2 border-b border-line px-3 py-1.5">
        <h4 className="text-xs font-semibold text-fg">{card.title}</h4>
        {card.note && <span className="text-2xs text-faint">{card.note}</span>}
      </header>

      {card.kind === "stats" && (
        <div className="grid grid-cols-2 gap-x-3 gap-y-2 p-3 sm:grid-cols-3">
          {card.stats.map((s) => (
            <div key={s.label} className="min-w-0">
              <div className="truncate text-2xs text-faint">{s.label}</div>
              <div
                className={cx(
                  "num truncate text-sm font-medium",
                  s.tone === "up" ? "text-up" : s.tone === "down" ? "text-down" : "text-fg",
                )}
              >
                {s.value}
              </div>
              {s.hint && <div className="truncate text-2xs text-faint">{s.hint}</div>}
            </div>
          ))}
        </div>
      )}

      {card.kind === "rows" && (
        <div className="divide-y divide-line/60">
          {card.rows.map((r, i) => (
            <RowLine key={i} r={r} />
          ))}
        </div>
      )}

      {card.kind === "bars" && (
        <div className="space-y-2 p-3">
          {card.bars.map((b) => {
            const w = Math.min(50, Math.abs(b.value) * 100 * 3);
            return (
              <div key={b.label}>
                <div className="flex items-baseline justify-between gap-2 text-2xs">
                  <span className="truncate text-muted">{b.label}</span>
                  <Change v={b.value} />
                </div>
                <div className="relative mt-1 h-1.5 rounded-full bg-surface-3">
                  <span className="absolute inset-y-0 left-1/2 w-px bg-line-strong" />
                  <span
                    className={cx("absolute inset-y-0 rounded-full", b.value >= 0 ? "bg-up" : "bg-down")}
                    style={b.value >= 0 ? { left: "50%", width: `${w}%` } : { right: "50%", width: `${w}%` }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      )}

      {card.kind === "definition" && <p className="p-3 text-xs leading-relaxed text-muted">{card.text}</p>}

      {card.kind === "steps" && (
        <ol className="list-decimal space-y-1.5 py-3 pr-3 pl-7 text-xs leading-relaxed text-muted">
          {card.steps.map((s, i) => (
            <li key={i}>{s}</li>
          ))}
        </ol>
      )}

      {card.kind === "spark" && card.points.length > 1 && (
        <div className="p-3">
          <Sparkline points={card.points} width={320} height={64} className="w-full" />
        </div>
      )}
    </section>
  );
}
