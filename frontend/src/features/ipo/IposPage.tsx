import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { EmptyState, ErrorState, Panel, SkeletonRows } from "../../components/ui/primitives";
import { api } from "../../lib/api";
import { fmtPrice, fmtStamp } from "../../lib/format";
import type { IpoIssue, IpoMood, IpoOverview } from "../../lib/types";
import { pct } from "../portfolio/format";
import { fmtDay } from "../tracker/StockStory";
import { Gain, HeadlineList, IssueCard, band, times } from "./parts";

function MoodCard({ m }: { m: IpoMood }) {
  return (
    <div className="rounded-lg border border-line bg-surface p-3.5">
      <div className="text-2xs tracking-wide text-faint uppercase">Last {m.days} days</div>
      {m.listed === 0 ? (
        <p className="mt-1 text-xs text-faint">No mainboard listings measured yet.</p>
      ) : (
        <div className="mt-1.5 grid grid-cols-3 gap-2">
          <div>
            <div className="num text-base font-semibold text-fg">{m.listed}</div>
            <div className="text-2xs text-faint">mainboard listings</div>
          </div>
          <div>
            <div className="num text-base font-semibold text-fg">{pct(m.above_issue_at_open, 0)}</div>
            <div className="text-2xs text-faint">opened above issue</div>
          </div>
          <div>
            <div className="text-base font-semibold">
              <Gain v={m.median_listing_gain} />
            </div>
            <div className="text-2xs text-faint">median listing gain</div>
          </div>
          {m.above_issue_now != null && (
            <p className="col-span-3 text-2xs text-muted">
              {pct(m.above_issue_now, 0)} of them trade above their issue price today.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function Section({ title, meta, children }: { title: string; meta?: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-2.5">
      <div className="flex flex-wrap items-baseline gap-x-3">
        <h2 className="text-xs font-semibold tracking-wide text-fg uppercase">{title}</h2>
        {meta && <span className="text-2xs text-faint">{meta}</span>}
      </div>
      {children}
    </section>
  );
}

function Cards({ items, ranked }: { items: IpoIssue[]; ranked?: boolean }) {
  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
      {items.map((i, k) => (
        <IssueCard key={i.symbol} i={i} rank={ranked ? k + 1 : undefined} />
      ))}
    </div>
  );
}

function RecentListings({ items }: { items: IpoIssue[] }) {
  const navigate = useNavigate();
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[760px] text-sm">
        <thead>
          <tr className="text-2xs tracking-wide text-faint uppercase">
            <th className="px-3 py-2 text-left font-medium">Company</th>
            <th className="px-3 py-2 text-left font-medium">Listed</th>
            <th className="px-3 py-2 text-right font-medium">Issue price</th>
            <th className="px-3 py-2 text-right font-medium" title="Institutional (QIB) subscription">
              QIB
            </th>
            <th className="px-3 py-2 text-right font-medium">Total</th>
            <th className="px-3 py-2 text-right font-medium" title="Listing-day open vs issue price">
              Listing gain
            </th>
            <th className="px-3 py-2 text-right font-medium">Price now</th>
            <th className="px-3 py-2 text-right font-medium">Since issue</th>
          </tr>
        </thead>
        <tbody>
          {items.map((i) => (
            <tr
              key={i.symbol}
              onClick={() => navigate(`/ipos/${encodeURIComponent(i.symbol)}`)}
              className="cursor-pointer border-t border-line hover:bg-surface-2"
            >
              <td className="max-w-64 px-3 py-2">
                <div className="truncate font-medium text-fg">{i.company}</div>
                <div className="text-2xs text-faint">{i.symbol}</div>
              </td>
              <td className="px-3 py-2 whitespace-nowrap text-muted">{fmtDay(i.listing_date)}</td>
              <td className="num px-3 py-2 text-right">{band(i)}</td>
              <td className="num px-3 py-2 text-right">{times(i.subscription?.qib)}</td>
              <td className="num px-3 py-2 text-right">{times(i.subscription?.total)}</td>
              <td className="px-3 py-2 text-right">
                <Gain v={i.listing?.listing_gain} />
              </td>
              <td className="num px-3 py-2 text-right" title={i.listing?.price_basis ?? undefined}>
                {i.listing?.price != null ? fmtPrice(i.listing.price) : "—"}
              </td>
              <td className="px-3 py-2 text-right">
                <Gain v={i.listing?.since_issue} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function OddsTable({ o }: { o: IpoOverview }) {
  return (
    <Panel
      title="How the track record is measured"
      meta={`${o.history_size} NSE mainboard IPOs${o.history_complete ? "" : " so far (still measuring)"}`}
    >
      <div className="space-y-3 p-3.5 text-xs text-muted">
        <p>
          For each past issue: institutional (QIB) demand at close, and its listing-day opening price against the issue
          price. An open or closed issue is matched with past issues in the same demand band. This is a record of what
          happened, not a forecast: a strong band still contains losers.
        </p>
        {o.odds_table.length > 0 && (
          <table className="w-full max-w-xl text-xs">
            <thead>
              <tr className="text-2xs tracking-wide text-faint uppercase">
                <th className="py-1 text-left font-medium">QIB demand</th>
                <th className="py-1 text-right font-medium">Issues</th>
                <th className="py-1 text-right font-medium">Opened higher</th>
                <th className="py-1 text-right font-medium">Average</th>
                <th className="py-1 text-right font-medium">Worst</th>
              </tr>
            </thead>
            <tbody>
              {o.odds_table.map((r) => (
                <tr key={r.bucket} className="border-t border-line">
                  <td className="py-1.5 text-fg">{r.bucket}</td>
                  <td className="num py-1.5 text-right">{r.sample}</td>
                  <td className="num py-1.5 text-right">{pct(r.above_issue, 0)}</td>
                  <td className="py-1.5 text-right">
                    <Gain v={r.average_gain} />
                  </td>
                  <td className="py-1.5 text-right">
                    <Gain v={r.worst} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </Panel>
  );
}

export function IposPage() {
  const q = useQuery({
    queryKey: ["ipos"],
    queryFn: api.ipos,
    refetchInterval: (query) => (query.state.data?.history_complete === false ? 30_000 : 5 * 60_000),
  });
  const o = q.data;
  const strongest = useMemo(() => {
    if (!o) return [];
    const all = new Map([...o.open, ...o.awaiting_listing].map((i) => [i.symbol, i]));
    return o.strongest.map((s) => all.get(s)).filter((i): i is IpoIssue => !!i);
  }, [o]);

  return (
    <div className="mx-auto flex max-w-[1200px] flex-col gap-5 p-3 sm:p-4">
      <div>
        <h1 className="text-lg font-semibold text-fg">IPOs</h1>
        <p className="text-xs text-muted">
          Live NSE subscription data, how recent listings performed, and IPO news.
          {o && ` Updated ${fmtStamp(o.as_of)}.`}
        </p>
      </div>
      {q.isPending ? (
        <Panel>
          <SkeletonRows rows={6} />
        </Panel>
      ) : q.isError ? (
        <Panel>
          <ErrorState error={q.error} />
        </Panel>
      ) : (
        o && (
          <>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              {o.mood.map((m) => (
                <MoodCard key={m.days} m={m} />
              ))}
            </div>

            <Section
              title="Strongest demand"
              meta="Open or recently closed issues ranked by how past issues with similar demand listed"
            >
              {strongest.length ? (
                <Cards items={strongest} ranked />
              ) : (
                <Panel>
                  <EmptyState title="Nothing to rank right now">
                    {o.open.length + o.awaiting_listing.length === 0
                      ? "No IPO is open for bidding or waiting to list. Rankings appear as soon as one opens."
                      : "Open issues have no demand figures yet, or the track record is still being measured."}
                  </EmptyState>
                </Panel>
              )}
            </Section>

            <Section title="Open for bidding" meta={`${o.open.length} issue${o.open.length === 1 ? "" : "s"}`}>
              {o.open.length ? (
                <Cards items={o.open} />
              ) : (
                <p className="text-xs text-faint">No IPO is open for bidding on NSE right now.</p>
              )}
            </Section>

            <Section title="Upcoming" meta="Announced on NSE with dates">
              {o.upcoming.length ? (
                <Cards items={o.upcoming} />
              ) : (
                <p className="text-xs text-faint">
                  NSE lists no dated upcoming issue yet. Companies that have filed papers or received SEBI approval show
                  up in the IPO news below before their dates are fixed.
                </p>
              )}
            </Section>

            {o.awaiting_listing.length > 0 && (
              <Section
                title="Closed, awaiting listing"
                meta="Allotment and listing usually follow within 3 working days"
              >
                <Cards items={o.awaiting_listing} />
              </Section>
            )}

            <Panel title="Recent listings" meta={`Mainboard, last 90 days · ${o.recent_listings.length} issues`}>
              {o.recent_listings.length ? (
                <RecentListings items={o.recent_listings} />
              ) : (
                <EmptyState title="No recent mainboard listings" />
              )}
            </Panel>

            <Panel title="IPO news" meta="Past 7 days">
              {o.news.length ? <HeadlineList items={o.news} /> : <EmptyState title="No IPO headlines found" />}
            </Panel>

            <OddsTable o={o} />
            {o.gaps.length > 0 && (
              <ul className="space-y-0.5 text-2xs text-caution">
                {o.gaps.map((g, k) => (
                  <li key={k}>{g}</li>
                ))}
              </ul>
            )}
            <p className="text-2xs text-faint">
              Sources: NSE issue data and subscription figures, Upstox exchange prices, Google News. Grey-market
              premiums are unofficial and are not used. Research and education only; not investment advice. Read the red
              herring prospectus before applying.
            </p>
          </>
        )
      )}
    </div>
  );
}
