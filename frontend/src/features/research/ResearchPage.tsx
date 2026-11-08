import { HeaderStat, PageHeader } from "../../components/PageHeader";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { IconExternal } from "../../components/ui/icons";
import { cx, EmptyState, ErrorState, Panel, SkeletonRows } from "../../components/ui/primitives";
import { api } from "../../lib/api";
import { fmtDateIST, fmtNumber, fmtStamp } from "../../lib/format";
import type { MacroIndicator, ResearchItem } from "../../lib/types";
import { AGENT_META, AGENT_ORDER, AgentCard, CompositeSummary, isBusy, SignalCell, StateLabel } from "./agents";
import { ResearchTimeline } from "./history";
import { ValidationPanel } from "./validation";

function MacroStrip({ indicators }: { indicators: MacroIndicator[] }) {
  return (
    <Panel title="Macro inputs" meta="Shared by every Macro agent run">
      <div className="grid grid-cols-2 gap-px bg-line sm:grid-cols-5">
        {indicators.map((m) => {
          const change =
            m.change == null
              ? "—"
              : `${m.change > 0 ? "+" : m.change < 0 ? "−" : ""}${fmtNumber(Math.abs(m.change), 2)}${m.change_unit === "%" ? "%" : " pp"}`;
          return (
            <div
              key={m.key}
              className="min-w-0 bg-surface px-3.5 py-2.5 odd:last:col-span-2 sm:odd:last:col-span-1"
              title={m.source}
            >
              <div className="truncate text-2xs tracking-wide text-faint uppercase">{m.label}</div>
              <div className="num mt-0.5 text-sm text-fg">
                {m.value == null ? "—" : `${fmtNumber(m.value, 2)}${m.unit === "%" ? "%" : ` ${m.unit}`}`}
              </div>
              <div className="num text-2xs text-muted">
                {change} {m.change != null && <span className="text-faint">over {m.change_window}</span>}
              </div>
              <div className={cx("text-2xs", m.stale ? "text-caution" : "text-faint")}>
                {m.problem ?? (m.as_of ? `as of ${fmtDateIST(m.as_of)}` : "no data")}
              </div>
            </div>
          );
        })}
      </div>
    </Panel>
  );
}

function ReportDetail({ item }: { item: ResearchItem }) {
  const qc = useQueryClient();
  const [pending, setPending] = useState(false);
  const report = item.report;
  const rerun = async () => {
    setPending(true);
    try {
      await api.runResearch(item.instrument.symbol);
      await qc.invalidateQueries({ queryKey: ["research"] });
    } finally {
      setPending(false);
    }
  };
  return (
    <section className="flex flex-col gap-3">
      <div className="rounded-lg border border-line bg-surface p-4">
        <div className="flex flex-wrap items-start gap-x-6 gap-y-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <Link
                to={`/stock/${encodeURIComponent(item.instrument.symbol)}`}
                className="text-lg font-semibold text-fg hover:text-accent"
              >
                {item.instrument.symbol}
              </Link>
              <StateLabel item={item} />
            </div>
            <p className="truncate text-sm text-muted">{item.instrument.name}</p>
            {report && (
              <p className="mt-1 text-2xs text-faint">
                {report.classification.industry ?? "Industry unclassified"}
                {report.classification.sector_index && ` · benchmark ${report.classification.sector_index}`}
                {report.classification.industry_source && ` · ${report.classification.industry_source}`}
              </p>
            )}
          </div>
          <div className="ml-auto flex flex-col items-end gap-2">
            {report && <CompositeSummary composite={report.composite} />}
            <button
              onClick={() => void rerun()}
              disabled={pending || isBusy(item)}
              className="rounded-md border border-line px-2.5 py-1 text-xs text-muted hover:border-line-strong hover:text-fg disabled:opacity-50"
            >
              {isBusy(item) ? "Running…" : "Run again"}
            </button>
          </div>
        </div>
        {item.state === "failed" && item.error && (
          <p className="mt-3 rounded-md border border-line bg-surface-2 px-3 py-2 text-xs text-muted">{item.error}</p>
        )}
      </div>
      {report ? (
        <>
          <ResearchTimeline symbol={item.instrument.symbol} />
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 2xl:grid-cols-4">
            {AGENT_ORDER.map((name) => {
              const output = report.agents.find((a) => a.agent === name);
              return output ? <AgentCard key={name} output={output} /> : null;
            })}
          </div>
          {report.headlines.length > 0 && (
            <Panel title="Headlines scored" meta="Google News search, last 30 days">
              <ul className="divide-y divide-line">
                {report.headlines.map((h) => (
                  <li key={h.link} className="flex items-start gap-3 px-3.5 py-2">
                    <a
                      href={h.link}
                      target="_blank"
                      rel="noreferrer noopener"
                      className="min-w-0 flex-1 text-sm text-fg hover:text-accent"
                    >
                      {h.title} <IconExternal className="inline text-faint" width={11} height={11} />
                    </a>
                    <span className="shrink-0 text-2xs whitespace-nowrap text-faint">
                      {h.publisher} · {fmtStamp(h.published_at)}
                    </span>
                  </li>
                ))}
              </ul>
            </Panel>
          )}
          <p className="text-2xs text-faint">
            Computed {fmtStamp(report.computed_at)} in {(report.duration_ms / 1000).toFixed(1)} s.{" "}
            {report.composite.method}. Peers: {report.classification.peers.join(", ") || "none"}
            {report.classification.peer_basis && ` (${report.classification.peer_basis})`}.
          </p>
        </>
      ) : (
        <div className="rounded-lg border border-line bg-surface">
          <EmptyState title={isBusy(item) ? "Research is running" : "No research yet"}>
            {isBusy(item)
              ? "The four agents are gathering data for this stock."
              : "Run the agents to produce a report."}
          </EmptyState>
        </div>
      )}
    </section>
  );
}

export function ResearchPage() {
  const [selected, setSelected] = useState<string | null>(null);
  const q = useQuery({
    queryKey: ["research"],
    queryFn: api.research,
    refetchInterval: (query) => (query.state.data?.items.some(isBusy) ? 3_000 : 60_000),
  });
  const items = q.data?.items ?? [];
  const current = items.find((i) => i.instrument.instrument_key === selected) ?? items[0];

  return (
    <div className="mx-auto flex max-w-[1680px] flex-col gap-3 p-3 sm:p-4">
      <PageHeader
        section="research"
        eyebrow="Four research agents"
        title="Research"
        subtitle={`Company, industry, economy and news agents score every stock you follow from −1 to +1, each with its evidence and data gaps. Reports refresh every ${q.data?.refresh_after_hours ?? 6} hours.`}
      >
        {items.length > 0 && <HeaderStat label="Covered">{items.length} stocks</HeaderStat>}
      </PageHeader>

      {q.data && q.data.macro.length > 0 && <MacroStrip indicators={q.data.macro} />}

      <Panel title="Watchlist coverage" meta={items.length ? `${items.length} stocks` : undefined}>
        {q.isPending ? (
          <SkeletonRows rows={4} />
        ) : q.isError ? (
          <ErrorState error={q.error} />
        ) : items.length === 0 ? (
          <EmptyState title="Your watchlist is empty">
            Add stocks from search or a stock page. Research starts automatically for each one.
          </EmptyState>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[820px] text-left text-sm">
              <thead>
                <tr className="border-b border-line text-2xs tracking-wide text-faint uppercase">
                  <th className="px-3.5 py-2 font-medium">Stock</th>
                  <th className="px-3 py-2 font-medium">Composite</th>
                  {AGENT_ORDER.map((a) => (
                    <th key={a} className="px-3 py-2 font-medium">
                      {AGENT_META[a].title}
                    </th>
                  ))}
                  <th className="px-3.5 py-2 text-right font-medium">Updated</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {items.map((item) => {
                  const active = item.instrument.instrument_key === current?.instrument.instrument_key;
                  return (
                    <tr
                      key={item.instrument.instrument_key}
                      onClick={() => setSelected(item.instrument.instrument_key)}
                      className={cx("cursor-pointer", active ? "bg-accent-soft" : "hover:bg-surface-2")}
                    >
                      <td className="px-3.5 py-2">
                        <div className="font-medium text-fg">{item.instrument.symbol}</div>
                        <div className="max-w-48 truncate text-2xs text-faint">
                          {item.report?.classification.industry ?? item.instrument.name}
                        </div>
                        {item.changes && item.changes.items.length > 0 && (
                          <div className="max-w-56 truncate text-2xs text-accent" title={item.changes.summary}>
                            {item.changes.summary}
                          </div>
                        )}
                      </td>
                      <td className="px-3 py-2">
                        <SignalCell output={item.report?.composite} />
                      </td>
                      {AGENT_ORDER.map((a) => (
                        <td key={a} className="px-3 py-2">
                          <SignalCell output={item.report?.agents.find((o) => o.agent === a)} />
                        </td>
                      ))}
                      <td className="px-3.5 py-2 text-right">
                        <StateLabel item={item} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      {current && <ReportDetail item={current} />}

      <ValidationPanel />

      <p className="text-2xs text-faint">
        Scores summarise the evidence shown; the track record below shows whether they have predicted returns. Research
        and education only.
      </p>
    </div>
  );
}
