import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
import { useLiveStatus } from "./live";
import type { MarketStatus } from "./types";

export function useMarketStatus(): MarketStatus | undefined {
  const { status } = useLiveStatus();
  const q = useQuery({ queryKey: ["market-status"], queryFn: api.marketStatus, refetchInterval: 60_000 });
  // The socket pushes exchange status changes; prefer it when newer.
  if (status?.market && (!q.data || status.market.as_of >= q.data.as_of)) return status.market;
  return q.data;
}

export function useMarketOpen(): boolean {
  return useMarketStatus()?.state === "open";
}

export function useAuthStatus() {
  return useQuery({ queryKey: ["auth"], queryFn: api.authStatus, refetchInterval: 60_000 });
}
