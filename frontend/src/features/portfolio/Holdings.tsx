import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { IconClose } from "../../components/ui/icons";
import { ErrorState, Skeleton } from "../../components/ui/primitives";
import { api } from "../../lib/api";
import { fmtPrice } from "../../lib/format";
import { rupees } from "./format";

interface Row {
  symbol: string;
  name: string | null;
  quantity: string;
  avgCost: string;
  price: number | null;
}

/** Quantities you own, so plans show real rebalancing moves. Stored locally in DuckDB only. */
export function HoldingsEditor({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const watch = useQuery({ queryKey: ["watchlist"], queryFn: api.watchlist });
  const held = useQuery({ queryKey: ["holdings"], queryFn: api.holdings });
  const [rows, setRows] = useState<Row[] | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (rows || !watch.data || !held.data) return;
    const bySym = new Map(held.data.map((h) => [h.symbol, h]));
    const equities = watch.data.filter((w) => w.instrument.segment === "NSE_EQ");
    const symbols = [...new Set([...equities.map((w) => w.instrument.symbol), ...held.data.map((h) => h.symbol)])];
    setRows(
      symbols.map((s) => {
        const h = bySym.get(s);
        const w = equities.find((e) => e.instrument.symbol === s);
        return {
          symbol: s,
          name: w?.instrument.name ?? h?.name ?? null,
          quantity: h ? String(h.quantity) : "",
          avgCost: h?.avg_cost != null ? String(h.avg_cost) : "",
          price: w?.quote?.ltp ?? h?.price ?? null,
        };
      }),
    );
  }, [rows, watch.data, held.data]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const set = (i: number, patch: Partial<Row>) =>
    setRows((rs) => rs!.map((r, k) => (k === i ? { ...r, ...patch } : r)));
  const total = (rows ?? []).reduce((t, r) => t + (Number(r.quantity) || 0) * (r.price ?? 0), 0);

  const save = async () => {
    if (!rows) return;
    setSaving(true);
    setError(null);
    try {
      await api.saveHoldings(
        rows
          .filter((r) => Number(r.quantity) > 0)
          .map((r) => ({
            symbol: r.symbol,
            quantity: Number(r.quantity),
            avg_cost: Number(r.avgCost) > 0 ? Number(r.avgCost) : null,
          })),
      );
      await Promise.all([
        qc.invalidateQueries({ queryKey: ["holdings"] }),
        qc.invalidateQueries({ queryKey: ["plan"] }),
        qc.invalidateQueries({ queryKey: ["brief"] }),
      ]);
      onClose();
    } catch (e) {
      setError(e);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-overlay p-0 sm:items-center sm:p-4"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal
        aria-label="My holdings"
        onClick={(e) => e.stopPropagation()}
        className="flex max-h-[90vh] w-full max-w-xl flex-col rounded-t-lg border border-line bg-surface sm:rounded-lg"
      >
        <header className="flex items-center gap-3 border-b border-line px-4 py-3">
          <div>
            <h2 className="text-sm font-semibold text-fg">My holdings</h2>
            <p className="text-2xs text-faint">
              Shares you own in your watchlist stocks. Saved on this computer only, used to work out rebalancing moves.
            </p>
          </div>
          <button onClick={onClose} className="ml-auto text-muted hover:text-fg" aria-label="Close">
            <IconClose />
          </button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto">
          {watch.isError || held.isError ? (
            <ErrorState error={watch.error ?? held.error} />
          ) : !rows ? (
            <Skeleton className="m-4 h-32" />
          ) : rows.length === 0 ? (
            <p className="p-4 text-sm text-muted">Add stocks to your watchlist first.</p>
          ) : (
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-line text-2xs tracking-wide text-faint uppercase">
                  <th className="px-4 py-1.5 font-medium">Stock</th>
                  <th className="px-2 py-1.5 font-medium">Shares</th>
                  <th className="px-2 py-1.5 font-medium">Avg cost (optional)</th>
                  <th className="px-4 py-1.5 text-right font-medium">Value</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {rows.map((r, i) => (
                  <tr key={r.symbol}>
                    <td className="px-4 py-2">
                      <div className="font-medium text-fg">{r.symbol}</div>
                      <div className="num text-2xs text-faint">{fmtPrice(r.price)}</div>
                    </td>
                    <td className="px-2 py-2">
                      <input
                        inputMode="decimal"
                        value={r.quantity}
                        onChange={(e) => set(i, { quantity: e.target.value.replace(/[^0-9.]/g, "") })}
                        placeholder="0"
                        aria-label={`${r.symbol} shares`}
                        className="num h-8 w-24 rounded-md border border-line bg-surface-2 px-2 text-fg outline-none focus:border-accent"
                      />
                    </td>
                    <td className="px-2 py-2">
                      <input
                        inputMode="decimal"
                        value={r.avgCost}
                        onChange={(e) => set(i, { avgCost: e.target.value.replace(/[^0-9.]/g, "") })}
                        placeholder="₹"
                        aria-label={`${r.symbol} average cost`}
                        className="num h-8 w-28 rounded-md border border-line bg-surface-2 px-2 text-fg outline-none focus:border-accent"
                      />
                    </td>
                    <td className="num px-4 py-2 text-right text-muted">
                      {rupees((Number(r.quantity) || 0) * (r.price ?? 0))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {error != null && <ErrorState error={error} compact />}
        </div>
        <footer className="flex items-center gap-3 border-t border-line px-4 py-3">
          <span className="num text-xs text-muted">Total {rupees(total)}</span>
          <button onClick={onClose} className="ml-auto rounded-md px-3 py-1.5 text-xs text-muted hover:text-fg">
            Cancel
          </button>
          <button
            onClick={() => void save()}
            disabled={saving || !rows}
            className="rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50"
          >
            {saving ? "Saving…" : "Save holdings"}
          </button>
        </footer>
      </div>
    </div>
  );
}
