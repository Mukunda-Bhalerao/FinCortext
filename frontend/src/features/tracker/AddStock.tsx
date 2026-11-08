import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { cx, Segmented } from "../../components/ui/primitives";
import { api } from "../../lib/api";
import type { Instrument } from "../../lib/types";

const input =
  "h-8 rounded-md border border-line bg-surface-2 px-2.5 text-sm text-fg placeholder:text-faint focus:border-accent focus:outline-none";

function todayIST(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(new Date());
}

function StockPicker({ value, onPick }: { value: Instrument | null; onPick: (i: Instrument | null) => void }) {
  const [text, setText] = useState("");
  const [debounced, setDebounced] = useState("");
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(text.trim()), 150);
    return () => clearTimeout(t);
  }, [text]);
  const q = useQuery({
    queryKey: ["search", debounced],
    queryFn: () => api.search(debounced),
    enabled: debounced.length > 0,
    staleTime: 60_000,
  });
  const results = (q.data ?? []).filter((i) => i.segment === "NSE_EQ");

  if (value) {
    return (
      <div className={cx(input, "flex items-center gap-2")}>
        <span className="font-medium">{value.symbol}</span>
        <span className="truncate text-xs text-faint">{value.name}</span>
        <button type="button" onClick={() => onPick(null)} className="ml-auto text-xs text-muted hover:text-fg">
          Change
        </button>
      </div>
    );
  }
  return (
    <div className="relative">
      <input
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        placeholder="Search an NSE stock"
        aria-label="Stock"
        className={cx(input, "w-full")}
      />
      {open && debounced && (
        <ul className="absolute z-20 mt-1 max-h-64 w-full overflow-auto rounded-md border border-line bg-surface shadow-lg">
          {results.length === 0 ? (
            <li className="px-3 py-2 text-xs text-faint">{q.isPending ? "Searching…" : "No NSE stock matches."}</li>
          ) : (
            results.map((i) => (
              <li key={i.instrument_key}>
                <button
                  type="button"
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => {
                    onPick(i);
                    setText("");
                    setOpen(false);
                  }}
                  className="flex w-full items-baseline gap-2 px-3 py-1.5 text-left hover:bg-surface-2"
                >
                  <span className="text-sm font-medium text-fg">{i.symbol}</span>
                  <span className="truncate text-xs text-faint">{i.name}</span>
                </button>
              </li>
            ))
          )}
        </ul>
      )}
    </div>
  );
}

export function AddStock({ portfolioId, onDone }: { portfolioId: string; onDone?: () => void }) {
  const qc = useQueryClient();
  const [stock, setStock] = useState<Instrument | null>(null);
  const [by, setBy] = useState<"quantity" | "amount">("quantity");
  const [size, setSize] = useState("");
  const [earlier, setEarlier] = useState(false);
  const [date, setDate] = useState("");
  const [price, setPrice] = useState("");

  const add = useMutation({
    mutationFn: () =>
      api.addPosition(portfolioId, {
        symbol: stock!.symbol,
        quantity: by === "quantity" ? Number(size) : null,
        amount: by === "amount" ? Number(size) : null,
        entry_date: earlier && date ? date : null,
        entry_price: earlier && price ? Number(price) : null,
      }),
    onSuccess: (p) => {
      qc.setQueryData(["tracked", portfolioId], p);
      void qc.invalidateQueries({ queryKey: ["tracked-review", portfolioId] });
      void qc.invalidateQueries({ queryKey: ["tracked"], exact: true });
      setStock(null);
      setSize("");
      setPrice("");
      onDone?.();
    },
  });

  const valid = !!stock && Number(size) > 0 && (!earlier || !!date);
  return (
    <form
      className="flex flex-col gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        if (valid) add.mutate();
      }}
    >
      <div className="grid grid-cols-1 gap-3 md:grid-cols-[minmax(0,2fr)_auto_minmax(0,1fr)]">
        <StockPicker value={stock} onPick={setStock} />
        <Segmented
          value={by}
          onChange={setBy}
          options={[
            { value: "quantity", label: "Shares" },
            { value: "amount", label: "Amount ₹" },
          ]}
        />
        <input
          type="number"
          min={1}
          step={by === "quantity" ? 1 : "any"}
          value={size}
          onChange={(e) => setSize(e.target.value)}
          placeholder={by === "quantity" ? "Number of shares" : "Rupees to invest"}
          aria-label={by === "quantity" ? "Number of shares" : "Rupees to invest"}
          className={input}
        />
      </div>
      <label className="flex items-center gap-2 text-xs text-muted">
        <input type="checkbox" checked={earlier} onChange={(e) => setEarlier(e.target.checked)} />I bought it earlier
      </label>
      {earlier && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="flex flex-col gap-1 text-2xs text-faint">
            Bought on
            <input
              type="date"
              max={todayIST()}
              value={date}
              onChange={(e) => setDate(e.target.value)}
              className={input}
            />
          </label>
          <label className="flex flex-col gap-1 text-2xs text-faint">
            Price paid per share (optional, else that day's close)
            <input
              type="number"
              min={0}
              step="any"
              value={price}
              onChange={(e) => setPrice(e.target.value)}
              placeholder="₹"
              className={input}
            />
          </label>
        </div>
      )}
      <div className="flex items-center gap-3">
        <button
          type="submit"
          disabled={!valid || add.isPending}
          className="h-8 rounded-md bg-accent px-3 text-xs font-medium text-white disabled:opacity-50"
        >
          {add.isPending ? "Adding…" : "Add to portfolio"}
        </button>
        <span className="text-2xs text-faint">
          {earlier ? "Priced at that day's close unless you give your price." : "Priced at the current market price."}
        </span>
      </div>
      {add.isError && <p className="text-xs text-down">{(add.error as Error).message}</p>}
    </form>
  );
}
