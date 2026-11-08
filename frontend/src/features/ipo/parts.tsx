import { Ring, StockAvatar } from "../../components/ui/visual";
import { Link } from "react-router-dom";
import { IconExternal } from "../../components/ui/icons";
import { cx } from "../../components/ui/primitives";
import { fmtPrice } from "../../lib/format";
import type { IpoIssue, IpoSubscription, ReviewHeadline } from "../../lib/types";
import { pct, rupees } from "../portfolio/format";
import { Signed } from "../tracker/PortfoliosPage";
import { fmtDay, inr } from "../tracker/StockStory";

export function times(v: number | null | undefined): string {
  if (v == null) return "—";
  return v >= 10 ? `${Math.round(v).toLocaleString("en-IN")}x` : `${v.toFixed(2)}x`;
}

export function band(i: IpoIssue): string {
  if (i.issue_price) return fmtPrice(i.issue_price, 0);
  if (i.price_low && i.price_high && i.price_low !== i.price_high)
    return `${fmtPrice(i.price_low, 0)}–${fmtPrice(i.price_high, 0).replace("₹", "")}`;
  if (i.price_high) return fmtPrice(i.price_high, 0);
  return "Price band not announced";
}

export function dates(i: IpoIssue): string {
  if (i.open_date && i.close_date) return `${fmtDay(i.open_date)} – ${fmtDay(i.close_date)}`;
  if (i.open_date) return `Opens ${fmtDay(i.open_date)}`;
  return "Dates not announced";
}

export function BoardBadge({ board }: { board: IpoIssue["board"] }) {
  return (
    <span
      className={cx(
        "rounded px-1.5 py-0.5 text-2xs font-medium",
        board === "sme" ? "bg-caution-soft text-caution" : "bg-surface-3 text-muted",
      )}
      title={board === "sme" ? "SME platform: smaller companies, higher risk, large lots" : "Mainboard issue"}
    >
      {board === "sme" ? "SME" : "Mainboard"}
    </span>
  );
}

const ROWS: { key: keyof IpoSubscription; label: string; hint: string }[] = [
  { key: "qib", label: "Institutions (QIB)", hint: "Mutual funds, insurers, foreign funds: the most informed bidders" },
  { key: "nii", label: "HNI (NII)", hint: "High-net-worth individuals and corporates bidding over ₹2 lakh" },
  { key: "retail", label: "Retail", hint: "Individuals bidding up to ₹2 lakh" },
  { key: "employee", label: "Employees", hint: "Employee reservation" },
  { key: "shareholder", label: "Shareholders", hint: "Reservation for shareholders of the parent company" },
  { key: "total", label: "Total", hint: "All categories together" },
];

/** Times subscribed per category on a log scale; the tick marks 1x (fully subscribed). */
export function SubscriptionBars({ s, compact }: { s: IpoSubscription; compact?: boolean }) {
  const max = Math.log10(1 + 300);
  const w = (v: number) => Math.min(100, (Math.log10(1 + v) / max) * 100);
  const one = w(1);
  const rows = ROWS.filter((r) => s[r.key] != null && (!compact || ["qib", "nii", "retail", "total"].includes(r.key)));
  return (
    <div className="space-y-1.5">
      {rows.map((r) => {
        const v = s[r.key] as number;
        return (
          <div key={r.key} className="grid grid-cols-[7.5rem_1fr_3.5rem] items-center gap-2 text-xs" title={r.hint}>
            <span className={cx("truncate", r.key === "total" ? "font-medium text-fg" : "text-muted")}>{r.label}</span>
            <div className="relative h-1.5 rounded-full bg-surface-3">
              <div
                className={cx(
                  "absolute inset-y-0 left-0 rounded-full",
                  v >= 1 ? (r.key === "qib" ? "bg-accent" : "bg-up") : "bg-caution",
                )}
                style={{ width: `${w(v)}%` }}
              />
              <div className="absolute -top-0.5 h-2.5 w-px bg-line-strong" style={{ left: `${one}%` }} />
            </div>
            <span className="num text-right text-fg">{times(v)}</span>
          </div>
        );
      })}
    </div>
  );
}

export function IssueCard({ i, rank }: { i: IpoIssue; rank?: number }) {
  return (
    <Link
      to={`/ipos/${encodeURIComponent(i.symbol)}`}
      className="fc-card flex flex-col gap-3 rounded-lg border border-line bg-surface p-4 hover:border-line-strong hover:bg-surface-2"
    >
      <div className="flex items-start gap-2">
        {rank != null && (
          <span className="num mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-accent-soft text-2xs font-semibold text-accent">
            {rank}
          </span>
        )}
        <StockAvatar symbol={i.symbol} size={34} />
        <div className="min-w-0">
          <h3 className="truncate text-sm font-semibold text-fg">{i.company}</h3>
          <div className="text-2xs text-faint">
            {i.symbol}
            {i.industry && ` · ${i.industry}`}
          </div>
        </div>
        <span className="ml-auto shrink-0">
          <BoardBadge board={i.board} />
        </span>
      </div>
      <div className="grid grid-cols-3 gap-2 text-xs">
        <div>
          <div className="text-2xs text-faint">Price</div>
          <div className="num text-fg">{band(i)}</div>
        </div>
        <div>
          <div className="text-2xs text-faint">Bidding</div>
          <div className="text-fg">{dates(i)}</div>
        </div>
        <div>
          <div className="text-2xs text-faint">Min. investment</div>
          <div className="num text-fg">{i.min_investment ? rupees(i.min_investment) : "—"}</div>
        </div>
      </div>
      {i.subscription ? (
        <SubscriptionBars s={i.subscription} compact />
      ) : (
        <p className="text-xs text-faint">
          {i.stage === "upcoming"
            ? "Demand figures appear once bidding opens."
            : "NSE has not published subscription figures for this issue."}
        </p>
      )}
      {i.subscription_note && <p className="text-2xs text-caution">{i.subscription_note}</p>}
      {i.odds && (
        <div className="rounded-md border border-line bg-surface-2 px-3 py-2">
          <div className="flex items-center gap-2.5">
            <Ring value={i.odds.above_issue} size={38} stroke={4} tone={i.odds.above_issue >= 0.6 ? "up" : "caution"}>
              <span className="num text-2xs font-semibold text-fg">{Math.round(i.odds.above_issue * 100)}</span>
            </Ring>
            <div>
              <span className="text-2xs tracking-wide text-faint uppercase">Track record</span>
              <div className="num text-sm font-semibold text-fg">
                {Math.round(i.odds.above_issue * 100)}% listed higher
              </div>
            </div>
          </div>
          <p className="mt-0.5 text-2xs leading-relaxed text-muted">{i.odds.text}</p>
        </div>
      )}
    </Link>
  );
}

export function HeadlineList({ items }: { items: ReviewHeadline[] }) {
  return (
    <ul className="divide-y divide-line">
      {items.map((h) => (
        <li key={h.link} className="flex gap-2.5 px-3.5 py-2.5 text-sm">
          <span
            className={cx(
              "mt-2 h-1.5 w-1.5 shrink-0 rounded-full",
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
            </div>
          </div>
        </li>
      ))}
    </ul>
  );
}

export function Signals({ items }: { items: string[] }) {
  if (!items.length) return null;
  return (
    <ul className="list-disc space-y-1 pl-4 text-xs text-muted">
      {items.map((s, k) => (
        <li key={k}>{inr(s)}</li>
      ))}
    </ul>
  );
}

export function Gain({ v }: { v: number | null | undefined }) {
  return <Signed v={v}>{pct(v, 1, true)}</Signed>;
}
