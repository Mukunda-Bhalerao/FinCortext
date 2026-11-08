import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { secStyle } from "../../components/PageHeader";
import { cx } from "../../components/ui/primitives";
import { AnimatedNumber, BreadthBar, Sparkline } from "../../components/ui/visual";
import { api } from "../../lib/api";
import { fmtNumber } from "../../lib/format";
import { mergeQuote, useLiveSubscription, useTick } from "../../lib/live";
import { useMarketOpen, useMarketStatus } from "../../lib/queries";
import { greeting, sessionClock } from "../../lib/session";
import { useSparklines } from "../../lib/sparklines";
import { pct, rupees } from "../portfolio/format";

const ACTIONS = [
  { to: "/portfolios", label: "Practise a trade", hint: "Virtual cash, live prices", section: "portfolios" as const },
  { to: "/lab", label: "Test an idea", hint: "Rules on years of real prices", section: "lab" as const },
  { to: "/ipos", label: "Check IPOs", hint: "Demand and recent listings", section: "ipos" as const },
  { to: "/learn", label: "Learn a term", hint: "Plain-language glossary", section: "learn" as const },
];

function useNow(ms: number) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), ms);
    return () => clearInterval(t);
  }, [ms]);
  return now;
}

function NiftyCard() {
  const marketOpen = useMarketOpen();
  const indices = useQuery({ queryKey: ["indices"], queryFn: api.indices, staleTime: 30_000 });
  const nifty = indices.data?.[0];
  const key = nifty?.instrument.instrument_key;
  useLiveSubscription([key]);
  const tick = useTick(key);
  const q = mergeQuote(nifty?.quote, tick, marketOpen);
  const spark = useSparklines([key])[key ?? ""];
  if (!nifty) return null;
  const up = (q.changePct ?? 0) >= 0;
  return (
    <Link
      to={`/?chart=${encodeURIComponent(nifty.instrument.instrument_key)}`}
      className="fc-card flex min-w-[220px] flex-1 flex-col gap-1 rounded-lg border border-line bg-surface/70 p-3"
    >
      <div className="flex items-center justify-between text-2xs text-faint">
        <span className="font-medium tracking-wide uppercase">{nifty.label}</span>
        <span>1 month</span>
      </div>
      <div className="flex items-end justify-between gap-3">
        <div>
          <div className="num text-xl font-semibold text-fg">
            <AnimatedNumber value={q.ltp} format={(v) => fmtNumber(v)} />
          </div>
          <div className={cx("num text-xs font-medium", up ? "text-up" : "text-down")}>
            {q.change != null && `${up ? "+" : ""}${fmtNumber(q.change)} (${pct((q.changePct ?? 0) / 100, 2, true)})`}
          </div>
        </div>
        <Sparkline points={spark} width={120} height={40} />
      </div>
    </Link>
  );
}

function BreadthCard() {
  const sectors = useQuery({ queryKey: ["sectors"], queryFn: api.sectors, staleTime: 60_000 });
  const items = sectors.data ?? [];
  if (!items.length) return null;
  const up = items.filter((i) => (i.quote?.change_pct ?? 0) > 0).length;
  const down = items.filter((i) => (i.quote?.change_pct ?? 0) < 0).length;
  const flat = items.length - up - down;
  const best = [...items].sort((a, b) => (b.quote?.change_pct ?? -99) - (a.quote?.change_pct ?? -99))[0];
  const worst = [...items].sort((a, b) => (a.quote?.change_pct ?? 99) - (b.quote?.change_pct ?? 99))[0];
  return (
    <Link
      to="/markets"
      className="fc-card flex min-w-[220px] flex-1 flex-col gap-2 rounded-lg border border-line bg-surface/70 p-3"
    >
      <div className="flex items-center justify-between text-2xs text-faint">
        <span className="font-medium tracking-wide uppercase">Sector breadth</span>
        <span>last session</span>
      </div>
      <div className="text-sm text-fg">
        <span className="num text-xl font-semibold">{up}</span>
        <span className="text-muted"> of {items.length} sectors up</span>
      </div>
      <BreadthBar up={up} down={down} flat={flat} />
      <div className="flex justify-between gap-2 text-2xs">
        {best && (
          <span className="truncate text-muted">
            Best <span className="text-up">{best.label}</span>
          </span>
        )}
        {worst && (
          <span className="truncate text-right text-muted">
            Weakest <span className="text-down">{worst.label}</span>
          </span>
        )}
      </div>
    </Link>
  );
}

/** The top of the dashboard: a hello, where the market is, how practice is going, and real
 * market context (NIFTY 50 trend and how many sectors rose). */
export function Welcome() {
  const market = useMarketStatus();
  const now = useNow(30_000);
  const accounts = useQuery({ queryKey: ["tracked"], queryFn: api.tracked, staleTime: 60_000 });
  const clock = sessionClock(now, market?.state);
  const paper = (accounts.data ?? []).filter((a) => a.kind === "paper");
  const best = [...paper].sort((a, b) => (b.account_value ?? 0) - (a.account_value ?? 0))[0];

  const marketLine =
    clock.phase === "open"
      ? `The market is open. ${clock.label}.`
      : clock.phase === "pre_open"
        ? `The pre-open auction is running; trading starts ${clock.label.replace("Pre-open · opens ", "")}.`
        : `The market is closed. ${clock.label} — orders you place now wait for it.`;

  return (
    <section
      className="fc-panel relative overflow-hidden rounded-xl border border-line bg-surface p-4 sm:p-5"
      style={secStyle("dashboard")}
    >
      <div className="fc-sec-glow pointer-events-none absolute -top-24 -left-20 h-64 w-64 opacity-40" aria-hidden />
      <div className="relative flex flex-col gap-4 lg:flex-row lg:items-center">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 text-2xs font-medium text-muted">
            <span
              className={cx(
                "h-1.5 w-1.5 rounded-full",
                clock.phase === "open"
                  ? "fc-ring bg-up text-up"
                  : clock.phase === "pre_open"
                    ? "bg-caution"
                    : "bg-faint",
              )}
            />
            {clock.phase === "open" ? "Market open" : clock.phase === "pre_open" ? "Pre-open" : "Market closed"} ·{" "}
            {clock.label}
          </div>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight text-fg">{greeting(now)}.</h1>
          <p className="mt-1 max-w-xl text-sm leading-relaxed text-muted">
            {marketLine}{" "}
            {best && best.account_return != null ? (
              <>
                Your practice account <span className="font-medium text-fg">{best.name}</span> is worth{" "}
                <span className="num font-medium text-fg">
                  <AnimatedNumber value={best.account_value} format={(v) => rupees(v)} />
                </span>
                ,{" "}
                <span
                  className={cx(
                    "num font-medium",
                    best.account_return > 0 ? "text-up" : best.account_return < 0 ? "text-down" : "text-fg",
                  )}
                >
                  {best.account_return === 0
                    ? "level with where it started"
                    : `${best.account_return > 0 ? "up" : "down"} ${pct(Math.abs(best.account_return), 2)}`}
                </span>
                .
              </>
            ) : (
              "Open a paper account to practise with virtual money before risking real money."
            )}
          </p>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {ACTIONS.map((a) => (
              <Link
                key={a.to}
                to={a.to}
                title={a.hint}
                style={secStyle(a.section)}
                className="group inline-flex items-center gap-1.5 rounded-full border border-line bg-surface/60 px-3 py-1 text-xs text-muted hover:border-[var(--sec)] hover:text-fg"
              >
                <span className="h-1.5 w-1.5 rounded-full bg-[var(--sec)]" />
                {a.label}
                <span className="inline-block transition-transform group-hover:translate-x-0.5">→</span>
              </Link>
            ))}
          </div>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row lg:w-[480px]">
          <NiftyCard />
          <BreadthCard />
        </div>
      </div>
    </section>
  );
}
