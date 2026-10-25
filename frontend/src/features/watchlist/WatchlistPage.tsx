import { WatchlistPanel } from "../dashboard/panels";

export function WatchlistPage() {
  return (
    <div className="mx-auto flex max-w-[1200px] flex-col gap-3 p-3 sm:p-4">
      <h1 className="text-lg font-semibold text-fg">Watchlist</h1>
      <WatchlistPanel />
      <p className="text-2xs text-faint">Click a column header to sort. Click a row to open the stock page.</p>
    </div>
  );
}
