import { useQuery } from "@tanstack/react-query";
import { cx, ErrorState, Panel, SkeletonRows } from "../../components/ui/primitives";
import { api } from "../../lib/api";
import { fmtStamp } from "../../lib/format";
import type { HealthComponent } from "../../lib/types";

const STATUS: Record<HealthComponent["status"], { label: string; dot: string; text: string }> = {
  ok: { label: "Working", dot: "bg-up", text: "text-up" },
  degraded: { label: "Degraded", dot: "bg-caution", text: "text-caution" },
  down: { label: "Down", dot: "bg-down", text: "text-down" },
  unknown: { label: "Not used yet", dot: "bg-faint", text: "text-faint" },
  off: { label: "Off", dot: "bg-line-strong", text: "text-faint" },
};

export function useHealth() {
  return useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 30_000, retry: false });
}

/** Every moving part and data source, with its latest success or failure. */
export function StatusPage() {
  const q = useHealth();
  const overall = q.data?.overall ?? "ok";
  return (
    <div className="mx-auto flex max-w-[1100px] flex-col gap-3 p-3 sm:p-4">
      <div>
        <h1 className="text-lg font-semibold text-fg">System status</h1>
        <p className="mt-1 text-sm text-muted">
          {q.isError
            ? "The backend is not answering."
            : overall === "ok"
              ? "Everything that is in use is working."
              : "Some parts are degraded; features that depend on them show their gaps instead of guessing."}
          {q.data?.started_at && ` Backend running since ${fmtStamp(q.data.started_at)}.`}
        </p>
      </div>
      <Panel title="Components" meta="Refreshes every 30 seconds">
        {q.isPending ? (
          <SkeletonRows rows={8} />
        ) : q.isError ? (
          <ErrorState error={q.error} />
        ) : (
          <ul className="divide-y divide-line">
            {(q.data.components ?? []).map((c) => {
              const s = STATUS[c.status];
              return (
                <li key={c.key} className="flex flex-wrap items-center gap-x-3 gap-y-0.5 px-3.5 py-2.5">
                  <span className={cx("h-2 w-2 rounded-full", s.dot)} aria-hidden />
                  <span className="min-w-40 text-sm font-medium text-fg">{c.label}</span>
                  <span className={cx("text-2xs font-medium", s.text)}>{s.label}</span>
                  <span className="w-full pl-5 text-2xs text-faint sm:ml-auto sm:w-auto sm:pl-0 sm:text-right">
                    {c.detail}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </Panel>
      <p className="text-2xs text-faint">
        The local database is backed up at each start (three copies kept in backend/data/backups) and restored
        automatically if it cannot be opened. Data sources are retried before a failure is reported.
      </p>
    </div>
  );
}
