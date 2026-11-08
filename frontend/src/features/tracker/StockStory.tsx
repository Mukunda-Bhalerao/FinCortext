import { StockAvatar } from "../../components/ui/visual";
import { useState } from "react";
import { Link } from "react-router-dom";
import { IconExternal } from "../../components/ui/icons";
import { cx } from "../../components/ui/primitives";
import { fmtPrice } from "../../lib/format";
import type { StockReview } from "../../lib/types";
import { pct, rupees } from "../portfolio/format";
import { Signed } from "./PortfoliosPage";

const DRIVER: Record<StockReview["driver"], string> = {
  market: "Moved with the market",
  sector: "Moved with its sector",
  stock: "Its own story",
  mixed: "Mixed causes",
};

/** Server sentences write rupees as "Rs" for the language model; show the symbol here. */
export const inr = (text: string) => text.replace(/Rs (?=\d)/g, "₹");

export function fmtDay(d: string | null | undefined): string {
  if (!d) return "";
  const date = new Date(d.length === 10 ? `${d}T12:00:00+05:30` : d);
  return new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", timeZone: "Asia/Kolkata" }).format(date);
}

/** A centred bar: green to the right for money made, red to the left for money lost. */
function ContributionBar({ share, value }: { share: number; value: number }) {
  const w = Math.min(50, Math.abs(share) * 50);
  return (
    <div className="relative h-1.5 w-full rounded-full bg-surface-3" aria-hidden>
      <div className="absolute inset-y-0 left-1/2 w-px bg-line-strong" />
      <div
        className={cx("absolute inset-y-0 rounded-full", value >= 0 ? "bg-up" : "bg-down")}
        style={value >= 0 ? { left: "50%", width: `${w}%` } : { right: "50%", width: `${w}%` }}
      />
    </div>
  );
}

function Part({ label, v, strong }: { label: string; v: number | null; strong?: boolean }) {
  return (
    <div className={cx("rounded-md border px-2 py-1", strong ? "border-accent/50 bg-accent-soft" : "border-line")}>
      <div className="truncate text-2xs text-faint">{label}</div>
      <Signed v={v} className="text-xs">
        {pct(v, 1, true)}
      </Signed>
    </div>
  );
}

export function StockStory({ s, defaultOpen }: { s: StockReview; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(!!defaultOpen);
  const sectorPart = s.sector_return != null && s.market_return != null ? s.sector_return - s.market_return : null;
  const hasEvidence =
    s.moves.length + s.headlines.length + s.dividends.length + s.events.length > 0 || s.research != null;
  return (
    <article className="rounded-lg border border-line bg-surface">
      <button
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full flex-col gap-2 p-3.5 text-left hover:bg-surface-2/50"
      >
        <div className="flex w-full items-center gap-2">
          <StockAvatar symbol={s.symbol} size={26} />
          <span className="text-sm font-semibold text-fg">{s.symbol}</span>
          <span className="hidden truncate text-xs text-faint sm:inline">{s.name}</span>
          <span className="ml-auto shrink-0 text-2xs text-faint">
            {Math.abs(s.return_pct) >= 0.0005 && DRIVER[s.driver]}
          </span>
          <Signed v={s.return_pct} className="w-16 shrink-0 text-right text-sm">
            {pct(s.return_pct, 1, true)}
          </Signed>
          <Signed v={s.contribution} className="w-20 shrink-0 text-right text-sm font-medium">
            {s.contribution > 0 ? "+" : ""}
            {rupees(s.contribution)}
          </Signed>
        </div>
        <ContributionBar share={s.contribution_share} value={s.contribution} />
        <p className="text-xs leading-relaxed text-muted">{inr(s.explanation)}</p>
      </button>
      {open && (
        <div className="flex flex-col gap-3 border-t border-line p-3.5">
          <div className="grid grid-cols-3 gap-2">
            <Part label="NIFTY 50" v={s.market_return} strong={s.driver === "market"} />
            <Part
              label={s.sector_label ? `${s.sector_label} vs market` : "Sector"}
              v={sectorPart}
              strong={s.driver === "sector"}
            />
            <Part
              label={s.sector_label ? "Beyond its sector" : "Beyond the market"}
              v={s.stock_specific}
              strong={s.driver === "stock"}
            />
          </div>
          <div className="text-2xs text-faint">
            {fmtPrice(s.start_price)} ({s.start_basis}) → {fmtPrice(s.end_price)} · {s.quantity} shares · {s.sector}
          </div>
          {s.moves.length > 0 && (
            <div>
              <h4 className="mb-1 text-2xs font-semibold tracking-wide text-faint uppercase">Big days</h4>
              <div className="flex flex-wrap gap-1.5">
                {s.moves.map((m) => (
                  <span key={m.date} className="rounded border border-line px-1.5 py-0.5 text-2xs">
                    <span className="text-muted">{m.live ? "Today so far" : fmtDay(m.date)}</span>{" "}
                    <Signed v={m.change_pct}>{pct(m.change_pct, 1, true)}</Signed>
                  </span>
                ))}
              </div>
            </div>
          )}
          {s.events.length > 0 && (
            <ul className="list-disc space-y-0.5 pl-4 text-xs text-muted">
              {s.events.map((e, i) => (
                <li key={i}>{e}</li>
              ))}
            </ul>
          )}
          {s.headlines.length > 0 && (
            <div>
              <h4 className="mb-1 text-2xs font-semibold tracking-wide text-faint uppercase">
                Reported in this period
              </h4>
              <ul className="space-y-1.5">
                {s.headlines.map((h) => (
                  <li key={h.link} className="flex gap-2 text-xs">
                    <span
                      className={cx(
                        "mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full",
                        h.tone === "positive" ? "bg-up" : h.tone === "negative" ? "bg-down" : "bg-faint",
                      )}
                      title={`Headline tone: ${h.tone}`}
                    />
                    <div className="min-w-0">
                      <a
                        href={h.link}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-fg hover:text-accent hover:underline"
                      >
                        {h.title}
                        <IconExternal className="ml-1 inline h-3 w-3 text-faint" />
                      </a>
                      <div className="text-2xs text-faint">
                        {h.publisher}
                        {h.published_at && ` · ${fmtDay(h.published_at)}`}
                        {h.near_move && <span className="text-accent"> · around the {fmtDay(h.near_move)} move</span>}
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
              <p className="mt-1.5 text-2xs text-faint">
                Headlines published around the moves. They give context; they are not proof of what caused them.
              </p>
            </div>
          )}
          {!hasEvidence && (
            <p className="text-xs text-faint">No big days, headlines, dividends or research changes in this period.</p>
          )}
          <Link
            to={`/stock/${encodeURIComponent(s.symbol)}`}
            className="self-start text-xs text-accent hover:underline"
          >
            Open {s.symbol} chart and research
          </Link>
        </div>
      )}
    </article>
  );
}
