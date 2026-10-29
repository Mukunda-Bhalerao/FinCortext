import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import type { Instrument } from "../lib/types";
import { IconSearch } from "./ui/icons";
import { cx } from "./ui/primitives";

/** Equities open their stock page; indices open on the dashboard chart. */
export function instrumentPath(i: Instrument): string {
  return i.segment === "NSE_EQ"
    ? `/stock/${encodeURIComponent(i.symbol)}`
    : `/?chart=${encodeURIComponent(i.instrument_key)}`;
}

export function SearchBox() {
  const [text, setText] = useState("");
  const [debounced, setDebounced] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  useEffect(() => {
    const t = setTimeout(() => setDebounced(text.trim()), 150);
    return () => clearTimeout(t);
  }, [text]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = e.target instanceof Element && e.target.closest("input, textarea");
      if ((e.key === "/" && !typing) || (e.key.toLowerCase() === "k" && (e.ctrlKey || e.metaKey))) {
        e.preventDefault();
        input.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const q = useQuery({
    queryKey: ["search", debounced],
    queryFn: () => api.search(debounced),
    enabled: debounced.length > 0,
    staleTime: 60_000,
  });
  const results = q.data ?? [];

  const pick = (i: Instrument) => {
    navigate(instrumentPath(i));
    setText("");
    setOpen(false);
    input.current?.blur();
  };

  return (
    <div className="relative w-full max-w-md">
      <div className="flex h-8 items-center gap-2 rounded-md border border-line bg-surface-2 px-2.5 focus-within:border-accent">
        <IconSearch className="shrink-0 text-faint" />
        <input
          ref={input}
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            setOpen(true);
            setActive(0);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 120)}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setActive((a) => Math.min(a + 1, results.length - 1));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setActive((a) => Math.max(a - 1, 0));
            } else if (e.key === "Enter" && results[active]) {
              pick(results[active]);
            } else if (e.key === "Escape") {
              setOpen(false);
              input.current?.blur();
            }
          }}
          placeholder="Search NSE stocks and indices"
          className="h-full w-full bg-transparent text-sm text-fg outline-none placeholder:text-faint"
          aria-label="Search instruments"
          role="combobox"
          aria-expanded={open}
        />
        <kbd className="hidden rounded border border-line px-1 text-2xs text-faint sm:block">/</kbd>
      </div>
      {open && debounced && (
        <div className="absolute top-9 right-0 left-0 z-50 overflow-hidden rounded-md border border-line-strong bg-surface shadow-xl">
          {q.isPending ? (
            <div className="px-3 py-2.5 text-xs text-faint">Searching</div>
          ) : q.isError ? (
            <div className="px-3 py-2.5 text-xs text-down">Search is unavailable right now.</div>
          ) : results.length === 0 ? (
            <div className="px-3 py-2.5 text-xs text-faint">No instruments match “{debounced}”.</div>
          ) : (
            <ul role="listbox">
              {results.map((r, i) => (
                <li key={r.instrument_key}>
                  <button
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => pick(r)}
                    onMouseEnter={() => setActive(i)}
                    className={cx(
                      "flex w-full items-center gap-3 px-3 py-2 text-left",
                      i === active && "bg-surface-3",
                    )}
                  >
                    <span className="w-28 shrink-0 truncate text-sm font-medium text-fg">{r.symbol}</span>
                    <span className="min-w-0 flex-1 truncate text-xs text-muted">{r.name}</span>
                    <span className="shrink-0 text-2xs text-faint">
                      {r.instrument_type === "INDEX" ? `${r.exchange} index` : r.exchange}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
