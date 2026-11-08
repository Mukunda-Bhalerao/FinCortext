import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { SearchBox } from "../components/SearchBox";
import { IconClose, IconMenu, IconMoon, IconSun } from "../components/ui/icons";
import { SECTION_ICON, secStyle, type Section } from "../components/PageHeader";
import { cx } from "../components/ui/primitives";
import { LOGIN_URL } from "../lib/api";
import { fmtTimeIST } from "../lib/format";
import { live, useLiveStatus } from "../lib/live";
import { useAuthStatus, useMarketStatus } from "../lib/queries";
import { useHealth } from "../features/status/StatusPage";
import { useStoredState } from "../lib/useStoredState";
import { AlertsBell } from "../features/alerts/AlertsBell";
import { Toaster } from "../components/Toaster";
import { StatusCard } from "./StatusCard";

type NavItem = { to: string; label: string; section: Section; hint: string };
const NAV_GROUPS: { title: string; items: NavItem[] }[] = [
  {
    title: "Markets",
    items: [
      { to: "/", label: "Dashboard", section: "dashboard", hint: "Today's market at a glance" },
      { to: "/markets", label: "Markets", section: "markets", hint: "Indices, sectors and the day's movers" },
      { to: "/watchlist", label: "Watchlist", section: "watchlist", hint: "Stocks you've starred, live" },
      { to: "/ipos", label: "IPOs", section: "ipos", hint: "Open issues, demand and recent listings" },
    ],
  },
  {
    title: "Practice",
    items: [
      { to: "/portfolios", label: "Portfolios", section: "portfolios", hint: "Paper trading and stocks you track" },
      { to: "/lab", label: "Strategy Lab", section: "lab", hint: "Test trading rules on years of real prices" },
    ],
  },
  {
    title: "Insight",
    items: [
      { to: "/research", label: "Research", section: "research", hint: "What the research engine thinks, and why" },
      { to: "/portfolio", label: "Planner", section: "planner", hint: "Plan a portfolio and test it on history" },
      { to: "/learn", label: "Learn", section: "learn", hint: "A learning path and every term explained" },
    ],
  },
];

/** The section a path belongs to, for the page's colour. */
function sectionOf(path: string): Section {
  const routes: [string, Section][] = [
    ["/markets", "markets"],
    ["/watchlist", "watchlist"],
    ["/ipos", "ipos"],
    ["/portfolios", "portfolios"],
    ["/lab", "lab"],
    ["/research", "research"],
    ["/stock", "research"],
    ["/portfolio", "planner"],
    ["/learn", "learn"],
  ];
  return routes.find(([prefix]) => path.startsWith(prefix))?.[1] ?? "dashboard";
}

function useTheme(): [string, () => void] {
  const [theme, setTheme] = useState(() => document.documentElement.dataset.theme ?? "dark");
  const toggle = () => {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem("fc-theme", next);
    } catch {
      /* storage unavailable: theme still applies for this visit */
    }
    setTheme(next);
  };
  return [theme, toggle];
}

function Clock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);
  return <span className="num hidden text-xs whitespace-nowrap text-muted lg:inline">{fmtTimeIST(now)}</span>;
}

function MarketPill() {
  const m = useMarketStatus();
  if (!m) return null;
  const label = m.state === "open" ? "Market open" : m.state === "pre_open" ? "Pre-open" : "Market closed";
  return (
    <span
      title={m.detail}
      className={cx(
        "inline-flex h-6 items-center gap-1.5 rounded-full border px-2.5 text-2xs font-medium whitespace-nowrap",
        m.state === "open" ? "border-up/30 text-up" : "border-line-strong text-muted",
      )}
    >
      <span className={cx("h-1.5 w-1.5 rounded-full", m.state === "open" ? "bg-up fc-pulse" : "bg-faint")} />
      {label}
    </span>
  );
}

function FeedPill() {
  const auth = useAuthStatus();
  const { status, socket } = useLiveStatus();
  if (auth.data && !auth.data.connected) {
    return (
      <a
        href={LOGIN_URL}
        title={auth.data.problem ?? undefined}
        className={cx(
          "inline-flex h-6 items-center rounded-full border px-2.5 text-2xs font-medium whitespace-nowrap",
          auth.data.oauth_configured
            ? "border-accent/50 text-accent hover:bg-accent-soft"
            : "pointer-events-none border-line-strong text-faint",
        )}
      >
        {auth.data.oauth_configured ? "Connect Upstox" : "Upstox not configured"}
      </a>
    );
  }
  let label = "Feed idle";
  let tone = "text-muted";
  if (socket !== "open") {
    label = "Reconnecting";
    tone = "text-caution";
  } else if (status?.state === "connected" && status.transport === "stream") {
    label = "Streaming";
    tone = "text-up";
  } else if (status?.state === "connected" && status.transport === "poll") {
    label = "Polling";
    tone = "text-accent";
  } else if (status?.state === "connecting") {
    label = "Connecting";
  } else if (status?.state === "disconnected") {
    label = "Feed interrupted";
    tone = "text-caution";
  }
  return (
    <span
      className={cx(
        "inline-flex h-6 items-center rounded-full border border-line-strong px-2.5 text-2xs font-medium whitespace-nowrap",
        tone,
      )}
      title={[
        auth.data?.user_name && `Upstox: ${auth.data.user_name}`,
        status?.detail,
        status?.latency?.provider_p50_ms != null &&
          `Exchange trade to feed: median ${(status.latency.provider_p50_ms / 1000).toFixed(2)} s, 90% within ${((status.latency.provider_p90_ms ?? 0) / 1000).toFixed(2)} s (${status.latency.samples} updates)`,
        status?.last_message_at && `Last feed message ${fmtTimeIST(status.last_message_at)}`,
        status?.silent?.length ? `${status.silent.length} instrument(s) not updating` : null,
      ]
        .filter(Boolean)
        .join(" · ")}
    >
      {label}
    </span>
  );
}

function ConnectNotice() {
  const location = useLocation();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [notice, setNotice] = useState<string | null>(null);
  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const result = params.get("upstox");
    if (!result) return;
    if (result === "connected") {
      setNotice("Upstox connected.");
      void qc.invalidateQueries();
      live.kick();
    } else {
      const reason = params.get("reason");
      setNotice(
        reason === "state"
          ? "Sign-in expired before it completed. Try connecting again."
          : reason === "denied"
            ? "Upstox sign-in was cancelled."
            : "Upstox sign-in failed. Check the API key, secret and redirect URL in .env.",
      );
    }
    params.delete("upstox");
    params.delete("reason");
    navigate({ search: params.toString() }, { replace: true });
  }, [location.search, navigate, qc]);
  if (!notice) return null;
  return (
    <div className="flex items-center gap-3 border-b border-line bg-accent-soft px-4 py-2 text-xs text-fg">
      {notice}
      <button className="ml-auto text-muted hover:text-fg" onClick={() => setNotice(null)} aria-label="Dismiss">
        <IconClose />
      </button>
    </div>
  );
}

function BackendBanner() {
  const h = useHealth();
  if (!h.isError) return null;
  return (
    <div className="flex items-center gap-3 border-b border-line bg-caution-soft px-4 py-2 text-xs text-fg">
      The FinCortext backend is not answering. Pages show their last data; start the backend and this clears itself.
    </div>
  );
}

function ConnectionBanner() {
  const auth = useAuthStatus();
  if (!auth.data || auth.data.connected) return null;
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-line bg-surface px-4 py-2 text-xs">
      <span className="text-muted">
        {auth.data.problem ?? "Upstox is not connected."} Market data is unavailable until you connect.
      </span>
      {auth.data.oauth_configured ? (
        <a href={LOGIN_URL} className="font-medium text-accent hover:underline">
          Connect Upstox
        </a>
      ) : (
        <span className="text-faint">Add UPSTOX_API_KEY and UPSTOX_API_SECRET to .env and restart the backend.</span>
      )}
    </div>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  const [theme, toggleTheme] = useTheme();
  const [navOpen, setNavOpen] = useState(false);
  // Desktop only: the mobile drawer always shows labels.
  const [collapsedPref, setCollapsedPref] = useStoredState<"0" | "1">("fc-sidebar-collapsed", "0");
  const collapsed = collapsedPref === "1" && !navOpen;
  const location = useLocation();
  useEffect(() => setNavOpen(false), [location.pathname]);

  return (
    <div className="flex h-full">
      <aside
        className={cx(
          "fixed inset-y-0 left-0 z-40 flex w-[var(--sidebar-w)] shrink-0 flex-col border-r border-line bg-surface transition-[transform,width] duration-200 md:static md:translate-x-0",
          navOpen ? "translate-x-0" : "-translate-x-full",
          collapsed && "md:w-14",
        )}
        aria-label="Main navigation"
      >
        <div
          className={cx(
            "flex h-[var(--topbar-h)] items-center gap-2.5 border-b border-line",
            collapsed ? "justify-center px-0" : "px-4",
          )}
        >
          <img
            src="/logo-mark.png"
            alt=""
            width={28}
            height={28}
            className="h-7 w-7 shrink-0 rounded-md bg-white ring-1 ring-line"
          />
          <span className={cx("text-[15px] font-semibold tracking-tight text-fg", collapsed && "sr-only")}>
            Fin<span className="text-accent">Cortext</span>
          </span>
        </div>
        <nav className="flex flex-col gap-3 overflow-y-auto p-2">
          {NAV_GROUPS.map((group) => (
            <div key={group.title} className="flex flex-col gap-0.5">
              {collapsed ? (
                <div className="mx-auto my-1 h-px w-6 bg-line" aria-hidden />
              ) : (
                <div className="px-2.5 pt-1 pb-1 text-2xs font-semibold tracking-wider text-faint uppercase">
                  {group.title}
                </div>
              )}
              {group.items.map(({ to, label, section, hint }) => {
                const Icon = SECTION_ICON[section];
                return (
                  <NavLink
                    key={to}
                    to={to}
                    end={to === "/" || to === "/portfolio"}
                    title={collapsed ? `${label}: ${hint}` : hint}
                    aria-label={collapsed ? label : undefined}
                    style={secStyle(section)}
                    className={({ isActive }) =>
                      cx(
                        "group relative flex h-8 items-center gap-2.5 rounded-md text-sm",
                        collapsed ? "justify-center px-0" : "px-2",
                        isActive
                          ? "fc-nav-active bg-surface-2 font-medium text-fg"
                          : "text-muted hover:translate-x-0.5 hover:bg-surface-2 hover:text-fg",
                      )
                    }
                  >
                    {({ isActive }) => (
                      <>
                        <span
                          className={cx(
                            "flex h-6 w-6 shrink-0 items-center justify-center rounded-md",
                            isActive ? "fc-sec-tile" : "group-hover:fc-sec-text",
                          )}
                        >
                          <Icon className={cx(!isActive && "transition-colors group-hover:text-[var(--sec)]")} />
                        </span>
                        <span className={cx("truncate", collapsed && "sr-only")}>{label}</span>
                      </>
                    )}
                  </NavLink>
                );
              })}
            </div>
          ))}
        </nav>
        <div
          className={cx("mt-auto border-t border-line text-2xs leading-relaxed text-faint", collapsed ? "p-2" : "p-3")}
        >
          <StatusCard compact={collapsed} />
          {!collapsed && (
            <p className="mt-2 px-2 text-2xs leading-relaxed text-faint">
              Practice money only. Nothing here is investment advice.
            </p>
          )}
          <button
            onClick={() => setCollapsedPref(collapsed ? "0" : "1")}
            className={cx(
              "mt-2 hidden h-7 items-center gap-2 rounded-md text-muted hover:bg-surface-2 hover:text-fg md:flex",
              collapsed ? "w-full justify-center" : "px-1.5",
            )}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            aria-expanded={!collapsed}
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
              className={cx("transition-transform", collapsed && "rotate-180")}
              aria-hidden
            >
              <rect x="3" y="4" width="18" height="16" rx="2" />
              <path d="M9 4v16M15 10l-2 2 2 2" />
            </svg>
            {!collapsed && <span>Collapse</span>}
          </button>
        </div>
      </aside>
      {navOpen && (
        <div className="fixed inset-0 z-30 bg-overlay md:hidden" onClick={() => setNavOpen(false)} aria-hidden />
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="fc-glass relative z-20 flex h-[var(--topbar-h)] shrink-0 items-center gap-3 border-b border-line px-3 sm:px-4">
          <button className="text-muted md:hidden" onClick={() => setNavOpen(true)} aria-label="Open navigation">
            <IconMenu />
          </button>
          <SearchBox />
          <div className="ml-auto flex items-center gap-2.5">
            <Clock />
            <span className="hidden sm:inline-flex">
              <MarketPill />
            </span>
            <FeedPill />
            <AlertsBell />
            <button
              onClick={toggleTheme}
              className="flex h-7 w-7 items-center justify-center rounded-md text-muted hover:bg-surface-2 hover:text-fg"
              aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
            >
              {theme === "dark" ? <IconSun /> : <IconMoon />}
            </button>
          </div>
        </header>
        <BackendBanner />
        <ConnectNotice />
        <ConnectionBanner />
        <main className="fc-ambient min-h-0 flex-1 overflow-y-auto" style={secStyle(sectionOf(location.pathname))}>
          {children}
        </main>
      </div>
      <Toaster />
    </div>
  );
}
