import { HeaderStat, PageHeader } from "../../components/PageHeader";
import { useQuery } from "@tanstack/react-query";
import { QuoteTable } from "../../components/QuoteTable";
import { ErrorState, Panel, SkeletonRows } from "../../components/ui/primitives";
import { api } from "../../lib/api";
import { useMarketOpen, useMarketStatus } from "../../lib/queries";
import { MoversPanel, SectorBoard } from "../dashboard/panels";

export function MarketsPage() {
  const marketOpen = useMarketOpen();
  const status = useMarketStatus();
  const indices = useQuery({
    queryKey: ["indices"],
    queryFn: api.indices,
    refetchInterval: marketOpen ? 30_000 : 300_000,
  });
  const sectors = useQuery({
    queryKey: ["sectors"],
    queryFn: api.sectors,
    refetchInterval: marketOpen ? 60_000 : 300_000,
  });

  return (
    <div className="mx-auto flex max-w-[1680px] flex-col gap-3 p-3 sm:p-4">
      <PageHeader
        section="markets"
        eyebrow="NSE · live"
        title="Markets"
        subtitle={status?.detail ?? "Benchmark and sector indices, the day's movers and where money is rotating."}
      >
        {sectors.data && (
          <HeaderStat label="Sectors up">
            {sectors.data.filter((s) => (s.quote?.change_pct ?? 0) > 0).length} / {sectors.data.length}
          </HeaderStat>
        )}
      </PageHeader>
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-12">
        <Panel title="Benchmark indices" className="lg:col-span-6">
          {indices.isPending ? (
            <SkeletonRows rows={5} />
          ) : indices.isError ? (
            <ErrorState error={indices.error} />
          ) : (
            <QuoteTable items={indices.data} sortable />
          )}
        </Panel>
        <Panel title="Sectoral indices" className="lg:col-span-6">
          {sectors.isPending ? (
            <SkeletonRows rows={10} />
          ) : sectors.isError ? (
            <ErrorState error={sectors.error} />
          ) : (
            <QuoteTable items={sectors.data} sortable />
          )}
        </Panel>
        <MoversPanel className="lg:col-span-6" count={15} />
        <SectorBoard className="lg:col-span-6" />
      </div>
    </div>
  );
}
