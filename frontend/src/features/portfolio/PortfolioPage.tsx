import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { EmptyState, ErrorState, Panel, Skeleton } from "../../components/ui/primitives";
import { api } from "../../lib/api";
import { fmtDateIST, fmtStamp } from "../../lib/format";
import type {
  InsightAction,
  PortfolioAnalysis,
  PortfolioPlan,
  PortfolioStatus,
  Preferences,
  Scenario,
} from "../../lib/types";
import { fmtScore, SignalBadge } from "../research/agents";
import { AskPanel } from "./Ask";
import { BriefHero } from "./Brief";
import { Evidence, Tag } from "./evidence";
import { pct } from "./format";
import { ScenarioCompare } from "./Compare";
import { GoalPlanner } from "./Goal";
import { HoldingsEditor } from "./Holdings";
import { MyPortfolio } from "./MyPortfolio";
import { useValidation } from "../research/validation";
import { ObjectivePicker, PlanWorkbench } from "./Plan";

const busy = (s: PortfolioStatus | undefined) => s?.state === "queued" || s?.state === "running";

/** Debounced value: plan requests fire once the user stops dragging or typing. */
function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

function SuggestedMoves({
  data,
  prefs,
  onTry,
}: {
  data: PortfolioAnalysis;
  prefs: Preferences;
  onTry: (p: Partial<Preferences>, label: string) => void;
}) {
  const trying = new Set(prefs.include);
  const items = data.candidates.slice(0, 6);
  if (!items.length) return null;
  return (
    <Panel
      title="Stocks that would diversify you"
      meta={`${data.candidates_screened} ${data.candidate_universe} stocks screened`}
      actions={<Tag kind="estimate" />}
    >
      <ul className="grid grid-cols-1 divide-y divide-line md:grid-cols-2 md:divide-y-0">
        {items.map((c) => {
          const v = c.validation;
          const held = v && v.vol_with != null && v.vol_without != null && v.vol_with < v.vol_without;
          const on = trying.has(c.symbol);
          return (
            <li key={c.symbol} className="flex flex-col gap-1.5 border-line p-3.5 md:border-b md:odd:border-r">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-semibold text-fg">{c.symbol}</span>
                <span className="text-2xs text-faint">{c.sector}</span>
                {c.new_sector && <span className="text-2xs text-accent">new sector</span>}
                {c.research_signal && (
                  <span className="inline-flex items-center gap-1">
                    <SignalBadge signal={c.research_signal} compact />
                    <span className="num text-2xs text-faint">{fmtScore(c.research_score)}</span>
                  </span>
                )}
              </div>
              <p className="text-xs leading-relaxed text-muted">
                Moves with your stocks only {c.avg_correlation < 0.2 ? "a little" : "partly"} (correlation{" "}
                <span className="num">{c.avg_correlation.toFixed(2)}</span>). Swings{" "}
                <span className="num">
                  {pct(c.vol_before, 1)} → {pct(c.vol_after, 1)}
                </span>{" "}
                at about <span className="num">{pct(c.weight_if_added, 0)}</span>.
              </p>
              {v ? (
                <p className="text-2xs text-faint">
                  <Tag kind="measured" /> {held ? "Also lowered" : "Did not lower"} swings in {fmtDateIST(v.start)} to{" "}
                  {fmtDateIST(v.end)}, a period the screen never saw ({pct(v.vol_without)} → {pct(v.vol_with)}).
                </p>
              ) : null}
              <div className="mt-1">
                <button
                  onClick={() =>
                    on
                      ? onTry({ include: prefs.include.filter((s) => s !== c.symbol) }, `Removed ${c.symbol}`)
                      : onTry({ include: [...prefs.include, c.symbol].slice(-8) }, `Trying ${c.symbol}`)
                  }
                  className={
                    on
                      ? "rounded-md border border-line px-2 py-0.5 text-2xs text-muted hover:text-fg"
                      : "rounded-md border border-accent/50 px-2 py-0.5 text-2xs font-medium text-accent hover:bg-accent-soft"
                  }
                >
                  {on ? "Stop trying" : "Try in plan"}
                </button>
              </div>
            </li>
          );
        })}
      </ul>
      {data.replacements.length > 0 && (
        <div className="border-t border-line px-3.5 py-3">
          <div className="mb-1.5 text-2xs tracking-wide text-faint uppercase">Or swap one</div>
          <ul className="space-y-1.5">
            {data.replacements.map((r) => (
              <li key={`${r.remove}-${r.add}`} className="flex flex-wrap items-center gap-2 text-xs text-muted">
                <span className="font-medium text-fg">
                  {r.remove} → {r.add}
                </span>
                <span className="num">
                  swings {pct(r.vol_before)} → {pct(r.vol_after)}
                </span>
                <button
                  onClick={() =>
                    onTry(
                      {
                        exclude: [...new Set([...prefs.exclude, r.remove])],
                        include: [...new Set([...prefs.include, r.add])].slice(-8),
                      },
                      `Swapped ${r.remove} for ${r.add}`,
                    )
                  }
                  className="text-2xs font-medium text-accent hover:underline"
                >
                  Try swap
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Panel>
  );
}

export function PortfolioPage() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const planRef = useRef<HTMLDivElement>(null);
  const status = useQuery({
    queryKey: ["portfolio"],
    queryFn: api.portfolio,
    refetchInterval: (query) => (busy(query.state.data) ? 3_000 : 120_000),
  });
  const saved = useQuery({ queryKey: ["preferences"], queryFn: api.preferences, staleTime: Infinity });
  const [prefs, setPrefs] = useState<Preferences | null>(null);
  const [undo, setUndo] = useState<{ prefs: Preferences; label: string } | null>(null);
  const [editing, setEditing] = useState(false);
  const [showEvidence, setShowEvidence] = useState(false);
  const [pinned, setPinned] = useState<PortfolioPlan | null>(null);
  const validation = useValidation();
  const researchVerdict = validation.data?.result?.tests.find((t) => t.key === "composite")?.verdict ?? null;
  useEffect(() => {
    if (saved.data && !prefs) setPrefs(saved.data);
  }, [saved.data, prefs]);

  const analysis = status.data?.result ?? null;
  const debounced = useDebounced(prefs, 350);
  const plan = useQuery({
    queryKey: ["plan", debounced, analysis?.computed_at],
    queryFn: () => api.plan(debounced!),
    enabled: !!debounced,
    placeholderData: keepPreviousData,
  });
  // Persist the latest choice on its own, so a background refetch of an older plan cannot undo it.
  const lastSaved = useRef<string | null>(null);
  useEffect(() => {
    if (!debounced) return;
    const body = JSON.stringify(debounced);
    if (lastSaved.current === null) {
      lastSaved.current = body;
      return;
    }
    if (body === lastSaved.current) return;
    lastSaved.current = body;
    void api.savePreferences(debounced).then(() => qc.invalidateQueries({ queryKey: ["brief"] }));
  }, [debounced, qc]);
  const brief = useQuery({
    queryKey: ["brief", plan.data?.computed_at],
    queryFn: api.brief,
    enabled: !!plan.data,
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });

  const change = useCallback((patch: Partial<Preferences>, label?: string) => {
    setPrefs((p) => {
      if (!p) return p;
      if (label) setUndo({ prefs: p, label });
      return { ...p, ...patch };
    });
  }, []);

  const scrollToPlan = () => planRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });

  const onAction = (a: InsightAction) => {
    if (!prefs) return;
    if (a.kind === "add" && a.symbol) {
      change({ include: [...new Set([...prefs.include, a.symbol])].slice(-8) }, `Trying ${a.symbol}`);
      scrollToPlan();
    } else if (a.kind === "remove" && a.symbol) {
      change({ exclude: [...new Set([...prefs.exclude, a.symbol])] }, `Without ${a.symbol}`);
      scrollToPlan();
    } else if (a.kind === "objective" && a.objective) {
      change({ objective: a.objective }, "Switched objective");
      scrollToPlan();
    } else if ((a.kind === "open_stock" || a.kind === "research") && a.symbol) {
      if (a.kind === "research") void api.runResearch(a.symbol);
      navigate(`/stock/${encodeURIComponent(a.symbol)}`);
    } else if (a.kind === "holdings") {
      setEditing(true);
    }
  };

  const onScenario = (s: Scenario) => {
    if (!prefs) return;
    change(
      {
        objective: s.objective ?? prefs.objective,
        include: [...new Set([...prefs.include, ...s.include])].slice(-8),
        exclude: [...new Set([...prefs.exclude, ...s.exclude])],
        max_weight: s.max_weight ?? prefs.max_weight,
        custom_weights: s.custom_weights ?? prefs.custom_weights ?? null,
      },
      s.label ?? "Scenario",
    );
    scrollToPlan();
  };

  const rerun = async () => {
    await api.runPortfolio();
    await qc.invalidateQueries({ queryKey: ["portfolio"] });
  };

  const weakest = plan.data?.assets.reduce<(typeof plan.data.assets)[number] | null>(
    (w, a) => (a.momentum != null && (w == null || (w.momentum ?? 0) > a.momentum) ? a : w),
    null,
  );
  const diversifier = analysis?.candidates[0]?.symbol;
  const suggestions = [
    weakest ? `Why is ${weakest.symbol} lagging?` : null,
    diversifier ? `What if I add ${diversifier}?` : null,
    "Compare the objectives",
    weakest ? `What if ${weakest.symbol} were 15%?` : null,
    "Can I reach 50 lakh in 10 years adding 10k a month?",
    "What is the biggest risk in this portfolio?",
  ].filter((x): x is string => !!x);
  const updating = plan.isFetching || (prefs !== debounced && !!plan.data);

  return (
    <div className="mx-auto flex max-w-[1680px] flex-col gap-4 p-3 sm:p-4">
      <div className="flex flex-wrap items-start gap-x-6 gap-y-2">
        <div className="min-w-0">
          <h1 className="text-lg font-semibold text-fg">Planner</h1>
          <p className="mt-0.5 max-w-3xl text-sm text-muted">
            What matters in your watchlist as a portfolio, the options worth considering, and how each would have
            behaved. Every number links back to its data.
          </p>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-3">
          <span className="text-2xs text-faint">
            {busy(status.data)
              ? "Refreshing the analysis…"
              : analysis
                ? `Prices to ${fmtDateIST(analysis.as_of)} · analysed ${fmtStamp(analysis.computed_at)}`
                : null}
          </span>
          <button
            onClick={() => setEditing(true)}
            className="rounded-md border border-line px-2.5 py-1 text-xs text-muted hover:border-line-strong hover:text-fg"
          >
            My holdings
          </button>
          <button
            onClick={() => void rerun()}
            disabled={busy(status.data)}
            className="rounded-md border border-line px-2.5 py-1 text-xs text-muted hover:border-line-strong hover:text-fg disabled:opacity-50"
          >
            {busy(status.data) ? "Running…" : "Refresh"}
          </button>
        </div>
      </div>

      {status.data?.state === "failed" && status.data.error && (
        <p className="rounded-md border border-line bg-surface px-3 py-2 text-xs text-muted">{status.data.error}</p>
      )}

      <MyPortfolio plan={plan.data} onEdit={() => setEditing(true)} />

      {status.isError ? (
        <div className="rounded-lg border border-line bg-surface">
          <ErrorState error={status.error} />
        </div>
      ) : brief.data ? (
        <BriefHero brief={brief.data} onAction={onAction} />
      ) : brief.isError ? null : (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <Skeleton className="h-28 rounded-lg md:col-span-3" />
          <Skeleton className="h-28 rounded-lg" />
          <Skeleton className="h-28 rounded-lg" />
          <Skeleton className="h-28 rounded-lg" />
        </div>
      )}

      <div ref={planRef} className="flex scroll-mt-4 flex-col gap-3">
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <h2 className="text-sm font-semibold text-fg">What are you aiming for?</h2>
            <p className="text-2xs text-faint">Pick an objective; the plan below updates as you change anything.</p>
          </div>
          <div className="ml-auto flex flex-wrap items-center gap-3">
            {plan.data && plan.data.assets.length > 0 && (
              <button
                onClick={() => setPinned(plan.data!)}
                className="rounded-md border border-line px-2 py-0.5 text-2xs text-muted hover:border-accent hover:text-accent"
                title="Keep this version to compare with the next change"
              >
                {pinned ? "Re-pin as A" : "Pin to compare"}
              </button>
            )}
            {undo && (
              <span className="fc-rise inline-flex items-center gap-2 rounded-full border border-accent/40 bg-accent-soft px-3 py-1 text-2xs text-fg">
                {undo.label}
                <button
                  onClick={() => {
                    setPrefs(undo.prefs);
                    setUndo(null);
                  }}
                  className="font-medium text-accent hover:underline"
                >
                  Undo
                </button>
              </span>
            )}
            {prefs &&
              (prefs.include.length > 0 ||
                prefs.exclude.length > 0 ||
                prefs.max_weight != null ||
                !!prefs.custom_weights) && (
                <button
                  onClick={() =>
                    change({ include: [], exclude: [], max_weight: null, custom_weights: null }, "Reset to watchlist")
                  }
                  className="text-2xs text-muted hover:text-fg"
                >
                  Reset to watchlist
                </button>
              )}
          </div>
        </div>
        {prefs && (
          <ObjectivePicker
            value={prefs.objective}
            previews={analysis?.objectives ?? []}
            onChange={(k) => change({ objective: k })}
          />
        )}
        {plan.isError && !plan.data ? (
          <div className="rounded-lg border border-line bg-surface">
            <ErrorState error={plan.error} />
          </div>
        ) : plan.data && prefs ? (
          plan.data.assets.length === 0 ? (
            <div className="rounded-lg border border-line bg-surface">
              <EmptyState title="Nothing to plan yet">
                {plan.data.backtest_note ?? "Add at least two stocks to your watchlist."}
              </EmptyState>
            </div>
          ) : (
            <PlanWorkbench
              plan={plan.data}
              prefs={prefs}
              updating={updating}
              onChange={(p) => change(p)}
              onEditHoldings={() => setEditing(true)}
              researchVerdict={researchVerdict}
            />
          )
        ) : (
          <Skeleton className="h-96 rounded-lg" />
        )}
        {pinned && plan.data && plan.data.assets.length > 0 && (
          <ScenarioCompare pinned={pinned} current={plan.data} onClear={() => setPinned(null)} />
        )}
        {prefs && plan.data?.backtest && <GoalPlanner prefs={prefs} />}
      </div>

      <div className="grid grid-cols-1 gap-3 xl:grid-cols-5">
        <div className="xl:col-span-3">
          {analysis && prefs && <SuggestedMoves data={analysis} prefs={prefs} onTry={change} />}
        </div>
        <div className="xl:col-span-2">
          {brief.data && <AskPanel ai={brief.data.ai} onScenario={onScenario} suggestions={suggestions} />}
        </div>
      </div>

      {analysis && (
        <section className="flex flex-col gap-3">
          <button
            onClick={() => setShowEvidence((v) => !v)}
            aria-expanded={showEvidence}
            className="flex flex-wrap items-center gap-2 self-start text-left text-sm font-medium text-muted hover:text-fg"
          >
            <span
              className={
                showEvidence ? "inline-block rotate-90 transition-transform" : "inline-block transition-transform"
              }
            >
              ›
            </span>
            Methods and evidence
            <span className="text-2xs font-normal text-faint">
              strategy comparison, correlations, candidate screen, selection check, assumptions
            </span>
          </button>
          {showEvidence && <Evidence data={analysis} />}
        </section>
      )}

      {plan.data && (
        <details className="rounded-lg border border-line bg-surface px-3.5 py-2.5 text-xs text-muted">
          <summary className="cursor-pointer text-2xs font-medium tracking-wide text-faint uppercase">
            Assumptions and limits of this plan
          </summary>
          <ul className="mt-2 space-y-1.5 leading-relaxed">
            {[...plan.data.assumptions, ...plan.data.limitations].map((l) => (
              <li key={l}>{l}</li>
            ))}
            {plan.data.excluded.map((e) => (
              <li key={e.symbol}>
                <span className="font-medium text-fg">{e.symbol} left out:</span> {e.reason}
              </li>
            ))}
          </ul>
        </details>
      )}

      <p className="text-2xs text-faint">
        For research and education. FinCortext is not a registered investment adviser; plans are calculations on past
        data and do not know your full finances, goals or tax position.
      </p>
      {editing && <HoldingsEditor onClose={() => setEditing(false)} />}
    </div>
  );
}
