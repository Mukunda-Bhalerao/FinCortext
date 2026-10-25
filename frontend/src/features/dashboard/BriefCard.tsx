import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { cx, Skeleton } from "../../components/ui/primitives";
import { api } from "../../lib/api";

const DOT = { high: "bg-down", medium: "bg-caution", low: "bg-faint" };

/** The portfolio brief in one card: headline and the three insights that matter most. */
export function BriefCard() {
  const q = useQuery({ queryKey: ["brief", "dashboard"], queryFn: api.brief, staleTime: 120_000, retry: 1 });
  if (q.isError) return null;
  return (
    <section className="rounded-lg border border-line bg-surface p-3.5">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="text-2xs font-medium tracking-wide text-accent uppercase">Your brief</span>
        <Link to="/portfolio" className="ml-auto text-2xs font-medium text-muted hover:text-accent">
          Open portfolio →
        </Link>
      </div>
      {q.isPending ? (
        <div className="mt-2 space-y-2">
          <Skeleton className="h-4 w-3/4" />
          <Skeleton className="h-3 w-1/2" />
        </div>
      ) : (
        <>
          <p className="mt-1 text-sm font-semibold text-fg sm:text-base">{q.data.headline}</p>
          {q.data.insights.length > 0 && (
            <ul className="mt-2 grid grid-cols-1 gap-x-6 gap-y-1.5 md:grid-cols-3">
              {q.data.insights.slice(0, 3).map((i) => (
                <li key={i.id} className="flex min-w-0 gap-2 text-xs">
                  <span className={cx("mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full", DOT[i.severity])} aria-hidden />
                  <span className="min-w-0">
                    <span className="font-medium text-fg">{i.title}</span>
                    <span className="block truncate text-faint" title={i.body}>
                      {i.body}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}
