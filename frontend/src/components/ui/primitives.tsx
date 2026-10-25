import type { ReactNode } from "react";
import { ApiError, LOGIN_URL } from "../../lib/api";
import { direction, fmtChange, fmtPct } from "../../lib/format";
import { useAuthStatus } from "../../lib/queries";
import type { Freshness } from "../../lib/types";

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

export function Panel({
  title,
  actions,
  meta,
  children,
  className,
  bodyClassName,
}: {
  title?: ReactNode;
  actions?: ReactNode;
  meta?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section className={cx("flex min-w-0 flex-col rounded-lg border border-line bg-surface", className)}>
      {(title || actions) && (
        <header className="flex min-h-10 flex-wrap items-center gap-x-3 gap-y-1 border-b border-line px-3.5 py-1.5">
          <h2 className="text-xs font-semibold tracking-wide text-fg uppercase">{title}</h2>
          {meta && <div className="truncate text-2xs text-faint">{meta}</div>}
          <div className="ml-auto flex items-center gap-2">{actions}</div>
        </header>
      )}
      <div className={cx("min-h-0 flex-1", bodyClassName)}>{children}</div>
    </section>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("fc-skeleton rounded", className)} />;
}

export function SkeletonRows({ rows = 6 }: { rows?: number }) {
  return (
    <div className="space-y-2.5 p-3.5">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex items-center gap-3">
          <Skeleton className="h-3 w-24" />
          <Skeleton className="ml-auto h-3 w-16" />
          <Skeleton className="h-3 w-12" />
        </div>
      ))}
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="flex h-full min-h-28 flex-col items-center justify-center gap-1 px-6 py-8 text-center">
      <p className="text-sm font-medium text-muted">{title}</p>
      {children && <div className="max-w-sm text-xs text-faint">{children}</div>}
    </div>
  );
}

export function ErrorState({ error, compact }: { error: unknown; compact?: boolean }) {
  const apiErr = error instanceof ApiError ? error : null;
  const auth = useAuthStatus();
  const message = apiErr?.message ?? "Something went wrong while loading this data.";
  return (
    <div
      className={cx(
        "flex h-full flex-col items-center justify-center gap-2 px-6 text-center",
        compact ? "min-h-20 py-4" : "min-h-28 py-8",
      )}
    >
      <p className="text-sm text-muted">{message}</p>
      {apiErr?.needsConnection && auth.data?.oauth_configured && (
        <a
          href={LOGIN_URL}
          className="rounded border border-line-strong px-2.5 py-1 text-xs font-medium text-fg hover:border-accent hover:text-accent"
        >
          Connect Upstox
        </a>
      )}
    </div>
  );
}

const FRESHNESS: Record<Freshness, { label: string; cls: string; dot: string }> = {
  live: { label: "Live", cls: "text-up", dot: "bg-up fc-pulse" },
  delayed: { label: "Polled", cls: "text-accent", dot: "bg-accent" },
  stale: { label: "Stale", cls: "text-caution", dot: "bg-caution" },
  last_close: { label: "Last close", cls: "text-muted", dot: "bg-faint" },
  unavailable: { label: "Unavailable", cls: "text-faint", dot: "bg-line-strong" },
};

export function FreshnessBadge({ freshness, title }: { freshness: Freshness; title?: string }) {
  const f = FRESHNESS[freshness];
  return (
    <span className={cx("inline-flex items-center gap-1.5 text-2xs font-medium", f.cls)} title={title}>
      <span className={cx("h-1.5 w-1.5 rounded-full", f.dot)} />
      {f.label}
    </span>
  );
}

export function ChangeText({
  change,
  pct,
  className,
  showAbs = true,
}: {
  change: number | null | undefined;
  pct: number | null | undefined;
  className?: string;
  showAbs?: boolean;
}) {
  const dir = direction(pct ?? change);
  return (
    <span
      className={cx(
        "num whitespace-nowrap",
        dir === "up" ? "text-up" : dir === "down" ? "text-down" : "text-muted",
        className,
      )}
    >
      {showAbs ? (
        <>
          {fmtChange(change)} <span>({fmtPct(pct)})</span>
        </>
      ) : (
        fmtPct(pct)
      )}
    </span>
  );
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  size = "sm",
}: {
  value: T;
  options: readonly { value: T; label: string; disabled?: boolean }[];
  onChange: (v: T) => void;
  size?: "sm" | "xs";
}) {
  return (
    <div className="inline-flex rounded-md border border-line bg-surface-2 p-0.5" role="tablist">
      {options.map((o) => (
        <button
          key={o.value}
          role="tab"
          aria-selected={o.value === value}
          disabled={o.disabled}
          onClick={() => onChange(o.value)}
          className={cx(
            "rounded px-2 font-medium transition-colors disabled:opacity-40",
            size === "sm" ? "h-6 text-xs" : "h-5 text-2xs",
            o.value === value ? "bg-surface-3 text-fg" : "text-muted hover:text-fg",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Stat({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="text-2xs tracking-wide text-faint uppercase">{label}</div>
      <div className="num mt-0.5 truncate text-sm text-fg">{value}</div>
      {sub && <div className="truncate text-2xs text-faint">{sub}</div>}
    </div>
  );
}
