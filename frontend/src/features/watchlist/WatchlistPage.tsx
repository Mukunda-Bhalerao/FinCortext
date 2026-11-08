import { PageHeader } from "../../components/PageHeader";
import { WatchlistPanel } from "../dashboard/panels";

export function WatchlistPage() {
  return (
    <div className="mx-auto flex max-w-[1200px] flex-col gap-3 p-3 sm:p-4">
      <PageHeader
        section="watchlist"
        title="Watchlist"
        subtitle="The stocks you follow, priced live. Starring a stock also keeps the research engine scoring it."
      />
      <WatchlistPanel />
      <p className="text-2xs text-faint">Click a column header to sort. Click a row to open the stock page.</p>
    </div>
  );
}
