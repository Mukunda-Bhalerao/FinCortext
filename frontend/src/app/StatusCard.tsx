import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";
import { cx } from "../components/ui/primitives";
import { useHealth } from "../features/status/StatusPage";
import { useMarketStatus } from "../lib/queries";
import { sessionClock } from "../lib/session";
import type { HealthComponent } from "../lib/types";

/** What each part does, in the words a user would use. Core parts keep prices and trading
 * working; the rest add context and can be missing without breaking anything. */
const PARTS: Record<string, { name: string; role: string; core: boolean }> = {
  database: { name: "Your data", role: "Saved portfolios, orders and research", core: true },
  upstox_auth: { name: "Upstox login", role: "Permission to read market data", core: true },
  live_feed: { name: "Live prices", role: "Streaming ticks for charts and orders", core: true },
  upstox: { name: "Price history", role: "Candles and quotes", core: true },
  instruments: { name: "Stock list", role: "Every NSE stock and index", core: true },
  research_worker: { name: "Research engine", role: "Scores stocks you follow", core: true },
  portfolio_engine: { name: "Planner engine", role: "Backtests and plans", core: true },
  news: { name: "News", role: "Headlines for stocks and IPOs", core: false },
  nse: { name: "IPO data", role: "Issues and subscription from NSE", core: false },
  yahoo: { name: "Company financials", role: "Results, ratios and dividends", core: false },
  fred: { name: "Economy data", role: "Rates and inflation for the macro view", core: false },
  llm: { name: "Written summaries", role: "Plain-language narration (needs Ollama)", core: false },
};

const DOT: Record<HealthComponent["status"], string> = {
  ok: "bg-up",
  degraded: "bg-caution",
  down: "bg-down",
  unknown: "bg-faint",
  off: "bg-faint",
};

function useNow(ms: number): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), ms);
    return () => clearInterval(t);
  }, [ms]);
  return now;
}

function summarise(parts: HealthComponent[], unreachable: boolean) {
  if (unreachable)
    return {
      tone: "down" as const,
      title: "Can't reach the server",
      note: "Start the backend; pages keep their last data.",
    };
  const core = parts.filter((p) => PARTS[p.key]?.core ?? true);
  const extra = parts.filter((p) => PARTS[p.key] && !PARTS[p.key]!.core);
  const coreDown = core.filter((p) => p.status === "down");
  const coreSlow = core.filter((p) => p.status === "degraded");
  const extraOut = extra.filter((p) => p.status === "down" || p.status === "degraded");
  const names = (xs: HealthComponent[]) => xs.map((p) => PARTS[p.key]?.name ?? p.label).join(", ");
  if (coreDown.length)
    return { tone: "down" as const, title: `${names(coreDown)} offline`, note: "Prices or trading may be stale." };
  if (coreSlow.length)
    return { tone: "degraded" as const, title: `${names(coreSlow)} slow`, note: "Retrying in the background." };
  return {
    tone: "ok" as const,
    title: "Everything's connected",
    note: extraOut.length ? `${names(extraOut)} paused. Nothing else is affected.` : null,
  };
}

/** Sidebar footer: whether the data you see is live, when the market opens or closes, and a
 * plain explanation of every source on hover. */
export function StatusCard({ compact }: { compact?: boolean }) {
  const health = useHealth();
  const market = useMarketStatus();
  const now = useNow(30_000);
  const [open, setOpen] = useState(false);
  const parts = health.data?.components ?? [];
  const s = summarise(parts, health.isError);
  const clock = sessionClock(now, market?.state);
  const dot = s.tone === "ok" ? "bg-up" : s.tone === "degraded" ? "bg-caution" : "bg-down";

  return (
    <div
      className="relative"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget)) setOpen(false);
      }}
    >
      <NavLink
        to="/status"
        aria-label={compact ? `${s.title}. ${clock.label}.` : undefined}
        className={cx("block rounded-md hover:bg-surface-2", compact ? "flex justify-center py-1.5" : "px-2 py-1.5")}
      >
        <span className="flex items-center gap-2">
          <span className={cx("relative h-2 w-2 shrink-0 rounded-full", dot, s.tone === "ok" && "fc-ring text-up")} />
          {!compact && <span className="truncate text-xs font-medium text-fg">{s.title}</span>}
        </span>
        {!compact && (
          <>
            {s.note && <span className="mt-0.5 block pl-4 text-2xs leading-snug text-faint">{s.note}</span>}
            <span className="mt-1.5 flex items-center gap-2 pl-4 text-2xs text-muted">
              <span className="num">{clock.label}</span>
            </span>
            {clock.progress != null && (
              <span className="mt-1 ml-4 block h-0.5 overflow-hidden rounded-full bg-surface-3">
                <span className="block h-full rounded-full bg-up/70" style={{ width: `${clock.progress * 100}%` }} />
              </span>
            )}
          </>
        )}
      </NavLink>
      {open && parts.length > 0 && (
        <div
          className={cx(
            "fc-toast absolute bottom-full z-50 mb-2 w-72 rounded-lg border border-line-strong bg-surface p-3 shadow-xl",
            compact ? "left-full ml-2" : "left-0",
          )}
          role="tooltip"
        >
          <p className="text-xs font-semibold text-fg">What's feeding this screen</p>
          <ul className="mt-2 space-y-1.5">
            {parts
              .filter((p) => PARTS[p.key])
              .sort((a, b) => Number(PARTS[b.key]!.core) - Number(PARTS[a.key]!.core))
              .map((p) => (
                <li key={p.key} className="flex gap-2 text-2xs" title={p.detail ?? undefined}>
                  <span className={cx("mt-1 h-1.5 w-1.5 shrink-0 rounded-full", DOT[p.status])} />
                  <span className="min-w-0">
                    <span className="text-fg">{PARTS[p.key]!.name}</span>
                    <span className="text-faint">
                      {" "}
                      · {p.status === "unknown" ? "not needed yet" : PARTS[p.key]!.role}
                    </span>
                  </span>
                </li>
              ))}
          </ul>
          <p className="mt-2 border-t border-line pt-2 text-2xs text-faint">Click for details and timings.</p>
        </div>
      )}
    </div>
  );
}
