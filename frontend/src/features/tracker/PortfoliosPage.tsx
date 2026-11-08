import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { EmptyState, ErrorState, Panel, SkeletonRows, cx } from "../../components/ui/primitives";
import { api } from "../../lib/api";
import { fmtAgo } from "../../lib/format";
import { useMarketOpen } from "../../lib/queries";
import type { TrackedPortfolioRow } from "../../lib/types";
import { pct, rupees } from "../portfolio/format";

export function Signed({
  v,
  children,
  className,
}: {
  v: number | null | undefined;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cx(
        "num",
        v == null ? "text-faint" : v > 0 ? "text-up" : v < 0 ? "text-down" : "text-muted",
        className,
      )}
    >
      {children}
    </span>
  );
}

function PortfolioCard({ p }: { p: TrackedPortfolioRow }) {
  const marketOpen = useMarketOpen();
  return (
    <Link
      to={`/portfolios/${p.id}`}
      className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4 transition-colors hover:border-line-strong hover:bg-surface-2"
    >
      <div className="flex items-baseline gap-2">
        <h2 className="truncate text-sm font-semibold text-fg">{p.name}</h2>
        <span className="ml-auto shrink-0 text-2xs text-faint">
          {p.positions} {p.positions === 1 ? "stock" : "stocks"}
        </span>
      </div>
      {p.positions === 0 ? (
        <p className="text-xs text-faint">No stocks yet. Open it to add some.</p>
      ) : (
        <div className="grid grid-cols-3 gap-3">
          <div>
            <div className="text-2xs tracking-wide text-faint uppercase">Value</div>
            <div className="num mt-0.5 text-sm text-fg">{rupees(p.value)}</div>
          </div>
          <div>
            <div className="text-2xs tracking-wide text-faint uppercase">Gain</div>
            <Signed v={p.pnl} className="mt-0.5 block text-sm">
              {pct(p.pnl_pct, 1, true)}
            </Signed>
          </div>
          <div>
            <div className="text-2xs tracking-wide text-faint uppercase">{marketOpen ? "Today" : "Last session"}</div>
            <Signed v={p.day_change_pct} className="mt-0.5 block text-sm">
              {pct(p.day_change_pct, 2, true)}
            </Signed>
          </div>
        </div>
      )}
      <div className="text-2xs text-faint">
        {p.last_viewed_at ? `Last opened ${fmtAgo(p.last_viewed_at)}` : `Created ${fmtAgo(p.created_at)}`}
      </div>
    </Link>
  );
}

export function PortfoliosPage() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const list = useQuery({ queryKey: ["tracked"], queryFn: api.tracked, refetchInterval: 60_000 });
  const [name, setName] = useState("");
  const create = useMutation({
    mutationFn: (n: string) => api.createTracked(n),
    onSuccess: (p) => {
      void qc.invalidateQueries({ queryKey: ["tracked"] });
      navigate(`/portfolios/${p.id}`);
    },
  });

  return (
    <div className="mx-auto flex max-w-[1200px] flex-col gap-4 p-3 sm:p-4">
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <h1 className="text-lg font-semibold text-fg">My Portfolios</h1>
          <p className="text-xs text-muted">
            Put stocks in a portfolio and come back later: each visit explains what changed since you last looked, and
            why.
          </p>
        </div>
        <form
          className="ml-auto flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (name.trim()) create.mutate(name.trim());
          }}
        >
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={60}
            placeholder="New portfolio name"
            aria-label="New portfolio name"
            className="h-8 w-52 rounded-md border border-line bg-surface-2 px-2.5 text-sm text-fg placeholder:text-faint focus:border-accent focus:outline-none"
          />
          <button
            type="submit"
            disabled={!name.trim() || create.isPending}
            className="h-8 rounded-md bg-accent px-3 text-sm font-medium text-white disabled:opacity-50"
          >
            Create
          </button>
        </form>
      </div>
      {create.isError && <p className="text-xs text-down">{(create.error as Error).message}</p>}
      {list.isPending ? (
        <Panel>
          <SkeletonRows rows={3} />
        </Panel>
      ) : list.isError ? (
        <Panel>
          <ErrorState error={list.error} />
        </Panel>
      ) : list.data.length === 0 ? (
        <Panel>
          <EmptyState title="No portfolios yet">
            Create one above, add the stocks you hold or want to follow, and open it again in a few days to see what
            happened.
          </EmptyState>
        </Panel>
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {list.data.map((p) => (
            <PortfolioCard key={p.id} p={p} />
          ))}
        </div>
      )}
      <p className="text-2xs text-faint">
        Prices come from your market data connection. Nothing here places orders. Research and education only.
      </p>
    </div>
  );
}
