import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { Link, useParams } from "react-router-dom";
import { EquityChart, type EquityLine } from "../../components/charts/EquityChart";
import { IconExternal } from "../../components/ui/icons";
import { EmptyState, ErrorState, Panel, SkeletonRows } from "../../components/ui/primitives";
import { api } from "../../lib/api";
import { fmtPrice, fmtStamp } from "../../lib/format";
import { rupees } from "../portfolio/format";
import { fmtDay } from "../tracker/StockStory";
import { BoardBadge, Gain, HeadlineList, Signals, SubscriptionBars, band, dates } from "./parts";

const STAGE = {
  upcoming: "Upcoming",
  open: "Open for bidding",
  closed: "Closed, awaiting listing",
  listed: "Listed",
} as const;

function Num({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="text-2xs tracking-wide text-faint uppercase">{label}</div>
      <div className="num mt-0.5 text-sm text-fg">{children}</div>
    </div>
  );
}

export function IpoDetailPage() {
  const { symbol } = useParams<{ symbol: string }>();
  const q = useQuery({
    queryKey: ["ipo", symbol],
    queryFn: () => api.ipo(symbol!),
    enabled: !!symbol,
    refetchInterval: (query) => (query.state.data?.issue.stage === "open" ? 120_000 : false),
  });
  const d = q.data;
  const lines = useMemo<EquityLine[]>(() => {
    if (!d || d.price_series.length < 2) return [];
    const issue = d.issue.issue_price;
    const out: EquityLine[] = [{ label: "Price", points: d.price_series, tone: "accent" }];
    if (issue)
      out.push({
        label: "Issue price",
        points: d.price_series.map((p) => ({ time: p.time, value: issue })),
        tone: "muted",
        dashed: true,
      });
    return out;
  }, [d]);

  if (q.isPending)
    return (
      <div className="mx-auto max-w-[1200px] p-3 sm:p-4">
        <Panel>
          <SkeletonRows rows={6} />
        </Panel>
      </div>
    );
  if (q.isError || !d)
    return (
      <div className="mx-auto max-w-[1200px] p-3 sm:p-4">
        <Panel>
          <ErrorState error={q.error} />
        </Panel>
      </div>
    );
  const i = d.issue;
  const l = i.listing;
  return (
    <div className="mx-auto flex max-w-[1200px] flex-col gap-4 p-3 sm:p-4">
      <div>
        <Link to="/ipos" className="text-2xs text-faint hover:text-fg">
          ← IPOs
        </Link>
        <div className="mt-0.5 flex flex-wrap items-center gap-2">
          <h1 className="text-lg font-semibold text-fg">{i.company}</h1>
          <BoardBadge board={i.board} />
          <span className="rounded bg-accent-soft px-1.5 py-0.5 text-2xs font-medium text-accent">
            {STAGE[i.stage]}
          </span>
        </div>
        <div className="text-xs text-faint">
          {i.symbol}
          {i.industry && ` · ${i.industry}`} · updated {fmtStamp(d.as_of)}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4 rounded-lg border border-line bg-surface p-4 sm:grid-cols-3 lg:grid-cols-6">
        <Num label={i.issue_price ? "Issue price" : "Price band"}>{band(i)}</Num>
        <Num label="Bidding">{dates(i)}</Num>
        <Num label="Lot">{i.lot_size ? `${i.lot_size} shares` : "—"}</Num>
        <Num label="Min. investment">{i.min_investment ? rupees(i.min_investment) : "—"}</Num>
        <Num label="Listing">{i.listing_date ? fmtDay(i.listing_date) : "—"}</Num>
        <Num label="Total demand">{i.subscription?.total != null ? `${i.subscription.total.toFixed(2)}x` : "—"}</Num>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Panel title="Who bid" meta="Times subscribed, all exchanges, from NSE">
          <div className="flex flex-col gap-3 p-3.5">
            {i.subscription ? (
              <SubscriptionBars s={i.subscription} />
            ) : (
              <p className="text-xs text-faint">
                {i.stage === "upcoming"
                  ? "Demand figures appear once bidding opens."
                  : "NSE has not published subscription figures for this issue."}
              </p>
            )}
            {i.subscription_note && <p className="text-2xs text-caution">{i.subscription_note}</p>}
            <p className="text-2xs text-faint">
              The line marks 1x (fully subscribed). Institutional demand has historically been the best single guide to
              how an issue lists.
            </p>
          </div>
        </Panel>
        <Panel title="What to weigh">
          <div className="flex flex-col gap-3 p-3.5">
            {i.odds ? (
              <div className="rounded-md border border-line bg-surface-2 px-3 py-2">
                <div className="text-2xs tracking-wide text-faint uppercase">Track record of similar issues</div>
                <p className="mt-0.5 text-xs leading-relaxed text-fg">{i.odds.text}</p>
              </div>
            ) : (
              <p className="text-xs text-faint">
                No track-record comparison yet: it needs final demand figures and enough comparable past issues.
              </p>
            )}
            <Signals items={i.signals} />
          </div>
        </Panel>
      </div>

      {i.stage === "listed" && l && (
        <Panel title="Since listing" meta={l.price_basis ? `Price ${l.price_basis}` : undefined}>
          <div className="grid grid-cols-2 gap-4 p-3.5 sm:grid-cols-4">
            <Num label="Listing-day open">{l.listing_open != null ? fmtPrice(l.listing_open) : "—"}</Num>
            <Num label="Listing gain">
              <Gain v={l.listing_gain} />
            </Num>
            <Num label="Price now">{l.price != null ? fmtPrice(l.price) : "—"}</Num>
            <Num label="Since issue">
              <Gain v={l.since_issue} />
            </Num>
          </div>
          {lines.length > 0 && (
            <div className="px-2 pb-2">
              <EquityChart lines={lines} unit="rupees" height={240} />
            </div>
          )}
          {l.instrument_key && (
            <div className="px-3.5 pb-3.5">
              <Link to={`/stock/${encodeURIComponent(i.symbol)}`} className="text-xs text-accent hover:underline">
                Open the {i.symbol} chart and research
              </Link>
            </div>
          )}
        </Panel>
      )}

      {(Object.keys(d.facts).length > 0 || d.lead_managers.length > 0) && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[2fr_1fr]">
          <Panel title="Issue details" meta="From NSE">
            <dl className="divide-y divide-line">
              {Object.entries(d.facts).map(([k, v]) => (
                <div key={k} className="grid grid-cols-[9rem_1fr] gap-3 px-3.5 py-2 text-xs">
                  <dt className="text-faint">{k}</dt>
                  <dd className="whitespace-pre-line text-fg">{v}</dd>
                </div>
              ))}
            </dl>
          </Panel>
          <div className="flex flex-col gap-4">
            {Object.keys(d.documents).length > 0 && (
              <Panel title="Documents">
                <ul className="space-y-1.5 p-3.5 text-xs">
                  {Object.entries(d.documents).map(([k, v]) => (
                    <li key={k}>
                      <a href={v} target="_blank" rel="noopener noreferrer" className="text-accent hover:underline">
                        {k}
                        <IconExternal className="ml-1 inline h-3 w-3" />
                      </a>
                    </li>
                  ))}
                </ul>
              </Panel>
            )}
            {d.lead_managers.length > 0 && (
              <Panel title="Lead managers">
                <ul className="space-y-1 p-3.5 text-xs text-muted">
                  {d.lead_managers.map((m) => (
                    <li key={m}>{m}</li>
                  ))}
                </ul>
              </Panel>
            )}
          </div>
        </div>
      )}

      <Panel title="News" meta="Past 30 days">
        {d.news.length ? <HeadlineList items={d.news} /> : <EmptyState title="No headlines found for this issue" />}
      </Panel>
      {d.gaps.length > 0 && (
        <ul className="space-y-0.5 text-2xs text-caution">
          {d.gaps.map((g, k) => (
            <li key={k}>{g}</li>
          ))}
        </ul>
      )}
      <p className="text-2xs text-faint">
        Research and education only; not investment advice. Read the red herring prospectus before applying.
      </p>
    </div>
  );
}
