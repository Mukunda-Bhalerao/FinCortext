import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

/** Recent daily closes for many instruments in one request, for trend lines in tables. */
export function useSparklines(keys: (string | null | undefined)[], days = 30): Record<string, number[]> {
  const list = useMemo(() => [...new Set(keys.filter((k): k is string => !!k))].sort().slice(0, 60), [keys.join(",")]);
  const q = useQuery({
    queryKey: ["sparklines", days, list.join(",")],
    queryFn: async () => {
      const resp = await fetch(`/api/market/sparklines?days=${days}&keys=${encodeURIComponent(list.join(","))}`);
      if (!resp.ok) return {};
      return (await resp.json()) as Record<string, number[]>;
    },
    enabled: list.length > 0,
    staleTime: 10 * 60_000,
    gcTime: 30 * 60_000,
    retry: false,
  });
  return q.data ?? {};
}
