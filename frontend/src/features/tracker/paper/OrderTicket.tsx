import { toast } from "../../../lib/toast";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Term } from "../../../components/Term";
import { cx, Segmented } from "../../../components/ui/primitives";
import { api } from "../../../lib/api";
import { fmtPrice } from "../../../lib/format";
import type { Instrument, OrderInput, OrderKind, OrderSide } from "../../../lib/types";
import { rupees } from "../../portfolio/format";
import { inr } from "../StockStory";

const input =
  "h-8 w-full rounded-md border border-line bg-surface-2 px-2.5 text-sm text-fg placeholder:text-faint focus:border-accent focus:outline-none";

export const TAGS = [
  "Results",
  "News",
  "Research signal",
  "Chart pattern",
  "Value",
  "Momentum",
  "Dip buy",
  "Long term",
  "Tip",
  "Experiment",
];

function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export function SymbolPicker({ value, onPick }: { value: string; onPick: (s: string) => void }) {
  const [text, setText] = useState("");
  const [open, setOpen] = useState(false);
  const q = useDebounced(text.trim(), 150);
  const search = useQuery({
    queryKey: ["search", q],
    queryFn: () => api.search(q),
    enabled: q.length > 0,
    staleTime: 60_000,
  });
  const results = (search.data ?? []).filter((i: Instrument) => i.segment === "NSE_EQ");
  if (value)
    return (
      <div className={cx(input, "flex items-center gap-2")}>
        <span className="font-medium">{value}</span>
        <button type="button" onClick={() => onPick("")} className="ml-auto text-xs text-muted hover:text-fg">
          Change
        </button>
      </div>
    );
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
        className={input}
      />
      {open && q && (
        <ul className="absolute z-20 mt-1 max-h-60 w-full overflow-auto rounded-md border border-line bg-surface shadow-lg">
          {results.length === 0 ? (
            <li className="px-3 py-2 text-xs text-faint">
              {search.isPending ? "Searching…" : "No NSE stock matches."}
            </li>
          ) : (
            results.map((i) => (
              <li key={i.instrument_key}>
                <button
                  type="button"
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => {
                    onPick(i.symbol);
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

function Field({ label, children }: { label: React.ReactNode; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-2xs text-faint">
      <span>{label}</span>
      {children}
    </label>
  );
}

const num = (s: string) => (s.trim() === "" ? null : Number(s));

export function OrderTicket({
  pid,
  initial,
  onDone,
}: {
  pid: string;
  initial?: { symbol?: string; side?: OrderSide; quantity?: number };
  onDone?: () => void;
}) {
  const qc = useQueryClient();
  const [symbol, setSymbol] = useState(initial?.symbol ?? "");
  const [side, setSide] = useState<OrderSide>(initial?.side ?? "BUY");
  const [kind, setKind] = useState<OrderKind>("MARKET");
  const [validity, setValidity] = useState<"DAY" | "GTC">("DAY");
  const [by, setBy] = useState<"qty" | "amount">(initial?.quantity ? "qty" : "amount");
  const [size, setSize] = useState(initial?.quantity ? String(initial.quantity) : "");
  const [limit, setLimit] = useState("");
  const [trigger, setTrigger] = useState("");
  const [reason, setReason] = useState("");
  const [tag, setTag] = useState<string | null>(null);
  const [target, setTarget] = useState("");
  const [stop, setStop] = useState("");

  const body: OrderInput | null = useMemo(() => {
    const n = Number(size);
    if (!symbol || !(n > 0)) return null;
    if (kind === "LIMIT" && !(Number(limit) > 0)) return null;
    if (kind === "SL" && !(Number(trigger) > 0)) return null;
    return {
      symbol,
      side,
      kind,
      validity,
      quantity: by === "qty" || side === "SELL" ? Math.floor(n) : null,
      amount: by === "amount" && side === "BUY" ? n : null,
      limit_price: kind === "LIMIT" ? Number(limit) : null,
      trigger_price: kind === "SL" ? Number(trigger) : null,
      reason: reason.trim() || null,
      tag,
      target_price: side === "BUY" ? num(target) : null,
      stop_price: side === "BUY" ? num(stop) : null,
    };
  }, [symbol, side, kind, validity, by, size, limit, trigger, reason, tag, target, stop]);
  const debounced = useDebounced(body, 350);
  const preview = useQuery({
    queryKey: ["order-preview", pid, debounced],
    queryFn: () => api.previewOrder(pid, debounced!),
    enabled: !!debounced,
    retry: false,
    staleTime: 10_000,
  });
  const place = useMutation({
    mutationFn: () => api.placeOrder(pid, body!),
    onSuccess: (o) => {
      const what = `${o.side === "BUY" ? "Buy" : "Sell"} ${o.quantity} ${o.symbol}`;
      if (o.status === "FILLED")
        toast(`${o.side === "BUY" ? "Bought" : "Sold"} ${o.quantity} ${o.symbol} at ${fmtPrice(o.fill_price)}`, {
          body: o.reason ? `Saved to your journal: “${o.reason}”` : "Filled at the live price.",
        });
      else if (o.status === "OPEN")
        toast(`${what} placed`, {
          tone: "info",
          body:
            o.kind === "MARKET"
              ? "The market is closed, so it fills at the first trade after the next open."
              : "It waits for its price. You'll get a note here when it fills.",
        });
      else toast(`${what} was ${o.status.toLowerCase()}`, { tone: "warning", body: o.message ?? undefined });
      for (const k of [["tracked", pid], ["activity", pid], ["tracked-review", pid], ["tracked"]])
        void qc.invalidateQueries({ queryKey: k });
      setSize("");
      setReason("");
      setTag(null);
      setTarget("");
      setStop("");
      onDone?.();
    },
  });
  const p = preview.data;
  const blocking = p?.warnings.some(
    (w) =>
      w.startsWith("Not enough") ||
      w.startsWith("You can sell") ||
      w.startsWith("The stop") ||
      w.startsWith("The target"),
  );

  return (
    <form
      className="flex flex-col gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        if (body && !blocking) place.mutate();
      }}
    >
      <div className="grid grid-cols-1 gap-3 md:grid-cols-[minmax(0,2fr)_auto_auto]">
        <SymbolPicker value={symbol} onPick={setSymbol} />
        <Segmented
          value={side}
          onChange={setSide}
          options={[
            { value: "BUY", label: "Buy" },
            { value: "SELL", label: "Sell" },
          ]}
        />
        <Segmented
          value={kind}
          onChange={setKind}
          options={[
            { value: "MARKET", label: "Market" },
            { value: "LIMIT", label: "Limit" },
            { value: "SL", label: "Stop-loss" },
          ]}
        />
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Field
          label={
            side === "BUY" ? (
              <span className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setBy("amount")}
                  className={by === "amount" ? "text-fg" : "hover:text-fg"}
                >
                  Amount ₹
                </button>
                <span>·</span>
                <button
                  type="button"
                  onClick={() => setBy("qty")}
                  className={by === "qty" ? "text-fg" : "hover:text-fg"}
                >
                  Shares
                </button>
              </span>
            ) : (
              "Shares"
            )
          }
        >
          <input
            type="number"
            min={1}
            step={by === "amount" && side === "BUY" ? "any" : 1}
            value={size}
            onChange={(e) => setSize(e.target.value)}
            placeholder={by === "amount" && side === "BUY" ? "₹10,000" : "10"}
            className={input}
          />
        </Field>
        {kind === "LIMIT" && (
          <Field label={<Term k="limit order">Limit price</Term>}>
            <input
              type="number"
              min={0}
              step="any"
              value={limit}
              onChange={(e) => setLimit(e.target.value)}
              className={input}
            />
          </Field>
        )}
        {kind === "SL" && (
          <Field label={<Term k="stop-loss">Trigger price</Term>}>
            <input
              type="number"
              min={0}
              step="any"
              value={trigger}
              onChange={(e) => setTrigger(e.target.value)}
              className={input}
            />
          </Field>
        )}
        {kind !== "MARKET" && (
          <Field label="Valid">
            <select value={validity} onChange={(e) => setValidity(e.target.value as "DAY" | "GTC")} className={input}>
              <option value="DAY">Today only</option>
              <option value="GTC">Until cancelled</option>
            </select>
          </Field>
        )}
        {side === "BUY" && (
          <>
            <Field label={<Term k="target">Target (optional)</Term>}>
              <input
                type="number"
                min={0}
                step="any"
                value={target}
                onChange={(e) => setTarget(e.target.value)}
                placeholder="Sell above"
                className={input}
              />
            </Field>
            <Field label={<Term k="stop-loss">Stop-loss (optional)</Term>}>
              <input
                type="number"
                min={0}
                step="any"
                value={stop}
                onChange={(e) => setStop(e.target.value)}
                placeholder="Sell below"
                className={input}
              />
            </Field>
          </>
        )}
      </div>
      <Field label={side === "BUY" ? "Why are you buying? (your journal)" : "Why are you selling?"}>
        <textarea
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          maxLength={500}
          rows={2}
          placeholder={
            side === "BUY"
              ? "e.g. Quarterly profit up 20%, price just above its 200-day average"
              : "e.g. Hit my target / the reason I bought no longer holds"
          }
          className="w-full rounded-md border border-line bg-surface-2 px-2.5 py-1.5 text-sm text-fg placeholder:text-faint focus:border-accent focus:outline-none"
        />
      </Field>
      {side === "BUY" && (
        <div className="flex flex-wrap gap-1.5">
          {TAGS.map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setTag(tag === t ? null : t)}
              className={cx(
                "rounded-full border px-2 py-0.5 text-2xs",
                tag === t ? "border-accent bg-accent-soft text-accent" : "border-line text-muted hover:text-fg",
              )}
            >
              {t}
            </button>
          ))}
        </div>
      )}

      {preview.isError && body && <p className="text-xs text-down">{(preview.error as Error).message}</p>}
      {p && body && (
        <div className="rounded-md border border-line bg-surface-2 p-3 text-xs">
          <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
            <span className="text-fg">
              {p.side === "BUY" ? "Buy" : "Sell"} <b>{p.quantity}</b> {p.symbol} × {fmtPrice(p.price)}
              <span className="text-faint"> ({p.price_basis})</span>
            </span>
            <span className="num ml-auto text-sm font-semibold text-fg">
              {p.side === "BUY" ? "You pay " : "You get "}
              {rupees(p.total)}
            </span>
          </div>
          <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-0.5 text-2xs text-muted sm:grid-cols-4">
            <span>Order value {rupees(p.value)}</span>
            <span>
              <Term k="STT">STT</Term> ₹{p.charges.stt.toFixed(0)}
            </span>
            {p.charges.stamp > 0 && (
              <span>
                <Term k="stamp duty">Stamp</Term> ₹{p.charges.stamp.toFixed(0)}
              </span>
            )}
            <span>Exchange + SEBI ₹{(p.charges.exchange + p.charges.sebi).toFixed(2)}</span>
            <span>GST ₹{p.charges.gst.toFixed(2)}</span>
            {p.charges.brokerage > 0 && <span>Brokerage ₹{p.charges.brokerage.toFixed(2)}</span>}
            {p.charges.dp > 0 && (
              <span>
                <Term k="DP charge">DP charge</Term> ₹{p.charges.dp.toFixed(2)}
              </span>
            )}
            <span className="font-medium text-fg">Charges ₹{p.charges.total.toFixed(2)}</span>
          </div>
          {p.break_even != null && (
            <p className="mt-1.5 text-2xs text-muted">
              <Term k="break-even">Break-even</Term>: the price must reach {fmtPrice(p.break_even)} (
              {(((p.break_even - p.price) / p.price) * 100).toFixed(2)}% above) before selling makes any money.
            </p>
          )}
          <p className="mt-1 text-2xs text-muted">
            {p.fills} Cash afterwards: {rupees(p.cash_after)}.
          </p>
          {p.warnings.map((w) => (
            <p key={w} className="mt-1 text-2xs text-caution">
              {inr(w)}
            </p>
          ))}
        </div>
      )}
      <div className="flex items-center gap-3">
        <button
          type="submit"
          disabled={!body || blocking || place.isPending}
          className={cx(
            "h-8 rounded-md px-4 text-sm font-medium text-white disabled:opacity-50",
            side === "BUY" ? "bg-up" : "bg-down",
          )}
        >
          {place.isPending ? "Placing…" : `Place ${side === "BUY" ? "buy" : "sell"} order`}
        </button>
        {!reason.trim() && side === "BUY" && body && (
          <span className="text-2xs text-faint">Tip: a written reason makes your journal and scorecard useful.</span>
        )}
        {place.isError && <span className="text-xs text-down">{(place.error as Error).message}</span>}
      </div>
    </form>
  );
}
