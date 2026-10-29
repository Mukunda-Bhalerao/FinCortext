import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { cx } from "../../components/ui/primitives";
import { api } from "../../lib/api";
import { fmtAgo } from "../../lib/format";
import type { FeedEvent } from "../../lib/types";
import { FactList } from "../portfolio/Brief";

const DOT = { high: "bg-down", medium: "bg-caution", low: "bg-faint" };
const KIND = {
  research: "Research",
  market: "Market",
  portfolio: "Portfolio",
  opportunity: "Option",
  data: "Data",
  results: "Results",
};

function Item({ e, onNavigate }: { e: FeedEvent; onNavigate: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <li className={cx("px-3.5 py-2.5", !e.seen && "bg-accent-soft/40")}>
      <div className="flex items-center gap-1.5 text-2xs text-faint">
        <span className={cx("h-1.5 w-1.5 rounded-full", DOT[e.severity])} aria-hidden />
        {KIND[e.kind]} · {fmtAgo(e.created_at)}
        {!e.seen && <span className="ml-auto text-accent">New</span>}
      </div>
      <p className="mt-0.5 text-sm font-medium text-fg">{e.title}</p>
      <p className="mt-0.5 text-xs leading-relaxed text-muted">{e.body}</p>
      <div className="mt-1.5 flex flex-wrap gap-3 text-2xs">
        {e.symbol && (
          <Link
            to={`/stock/${encodeURIComponent(e.symbol)}`}
            onClick={onNavigate}
            className="text-muted hover:text-accent"
          >
            Open {e.symbol}
          </Link>
        )}
        <Link
          to={`/portfolio?ask=${encodeURIComponent(`Why does this matter for my portfolio: ${e.title}?`)}`}
          onClick={onNavigate}
          className="font-medium text-accent hover:underline"
        >
          Ask about this
        </Link>
        {e.facts.length > 0 && (
          <button onClick={() => setOpen((v) => !v)} className="text-faint hover:text-fg" aria-expanded={open}>
            {open ? "Hide evidence" : "Evidence"}
          </button>
        )}
      </div>
      {open && (
        <div className="mt-2 border-t border-line pt-2">
          <FactList facts={e.facts} />
        </div>
      )}
    </li>
  );
}

/** What FinCortext noticed since you last looked. */
export function AlertsBell() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const q = useQuery({ queryKey: ["events"], queryFn: api.events, refetchInterval: 60_000, retry: false });
  const unread = q.data?.unread ?? 0;

  useEffect(() => {
    if (!open) return;
    const onDown = (ev: MouseEvent) => {
      if (box.current && !box.current.contains(ev.target as Node)) setOpen(false);
    };
    const onKey = (ev: KeyboardEvent) => ev.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    const t = unread
      ? setTimeout(() => void api.markSeen().then(() => qc.invalidateQueries({ queryKey: ["events"] })), 2500)
      : undefined;
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
      if (t) clearTimeout(t);
    };
  }, [open, unread, qc]);

  return (
    <div ref={box} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="relative flex h-7 w-7 items-center justify-center rounded-md text-muted hover:bg-surface-2 hover:text-fg"
        aria-label={unread ? `${unread} new alerts` : "Alerts"}
        aria-expanded={open}
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
          aria-hidden
        >
          <path d="M6 8a6 6 0 1112 0c0 7 3 8 3 8H3s3-1 3-8" />
          <path d="M10.3 21a1.9 1.9 0 003.4 0" />
        </svg>
        {unread > 0 && (
          <span className="num absolute -top-0.5 -right-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-accent px-1 text-[10px] font-semibold text-white">
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </button>
      {open && (
        <div className="fixed inset-x-3 top-14 z-50 flex max-h-[75vh] flex-col overflow-hidden rounded-lg border border-line bg-surface shadow-xl sm:absolute sm:inset-x-auto sm:top-9 sm:right-0 sm:w-[400px]">
          <div className="flex items-center border-b border-line px-3.5 py-2">
            <span className="text-xs font-semibold text-fg">What FinCortext noticed</span>
            <span className="ml-auto text-2xs text-faint">Checked every 10 minutes</span>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">
            {q.isError ? (
              <p className="p-3.5 text-xs text-muted">Alerts are unavailable while the backend is unreachable.</p>
            ) : !q.data?.events.length ? (
              <p className="p-3.5 text-xs text-muted">
                Nothing yet. Research changes, unusual moves in your stocks, drift from your plan and new diversifiers
                appear here.
              </p>
            ) : (
              <ul className="divide-y divide-line">
                {q.data.events.map((e) => (
                  <Item key={e.id} e={e} onNavigate={() => setOpen(false)} />
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
