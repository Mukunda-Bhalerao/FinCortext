// Number and time formatting. Indian digit grouping, IST display.

const DASH = "—";
const cache = new Map<string, Intl.NumberFormat>();

function nf(min: number, max: number): Intl.NumberFormat {
  const id = `${min}:${max}`;
  let f = cache.get(id);
  if (!f) {
    f = new Intl.NumberFormat("en-IN", { minimumFractionDigits: min, maximumFractionDigits: max });
    cache.set(id, f);
  }
  return f;
}

const ok = (v: number | null | undefined): v is number => typeof v === "number" && Number.isFinite(v);

/** 1,23,456.78 */
export function fmtNumber(v: number | null | undefined, decimals = 2): string {
  return ok(v) ? nf(decimals, decimals).format(v) : DASH;
}

/** ₹1,23,456.78 */
export function fmtPrice(v: number | null | undefined, decimals = 2): string {
  return ok(v) ? `₹${nf(decimals, decimals).format(v)}` : DASH;
}

/** Index levels are points, not rupees. */
export function fmtLevel(v: number | null | undefined): string {
  return fmtNumber(v, 2);
}

export function fmtChange(v: number | null | undefined, decimals = 2): string {
  if (!ok(v)) return DASH;
  const s = nf(decimals, decimals).format(Math.abs(v));
  return v > 0 ? `+${s}` : v < 0 ? `−${s}` : s;
}

export function fmtPct(v: number | null | undefined): string {
  return ok(v) ? `${fmtChange(v, 2)}%` : DASH;
}

/** 1.24 Cr, 35.6 L, 12.4K */
export function fmtCompact(v: number | null | undefined): string {
  if (!ok(v)) return DASH;
  const a = Math.abs(v);
  if (a >= 1e7) return `${nf(2, 2).format(v / 1e7)} Cr`;
  if (a >= 1e5) return `${nf(2, 2).format(v / 1e5)} L`;
  if (a >= 1e3) return `${nf(1, 1).format(v / 1e3)}K`;
  return nf(0, 0).format(v);
}

export function direction(v: number | null | undefined): "up" | "down" | "flat" {
  if (!ok(v) || v === 0) return "flat";
  return v > 0 ? "up" : "down";
}

const timeIST = new Intl.DateTimeFormat("en-IN", {
  timeZone: "Asia/Kolkata",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});
const dateTimeIST = new Intl.DateTimeFormat("en-IN", {
  timeZone: "Asia/Kolkata",
  day: "2-digit",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});
const dateIST = new Intl.DateTimeFormat("en-IN", {
  timeZone: "Asia/Kolkata",
  day: "2-digit",
  month: "short",
  year: "numeric",
});

const toDate = (v: string | number | Date) => (v instanceof Date ? v : new Date(v));

export function fmtTimeIST(v: string | number | Date | null | undefined): string {
  return v == null ? DASH : `${timeIST.format(toDate(v))} IST`;
}

export function fmtDateTimeIST(v: string | number | Date | null | undefined): string {
  return v == null ? DASH : `${dateTimeIST.format(toDate(v))} IST`;
}

export function fmtDateIST(v: string | number | Date | null | undefined): string {
  return v == null ? DASH : dateIST.format(toDate(v));
}

/** Same IST calendar day shows time only; otherwise date and time. */
export function fmtStamp(v: string | number | Date | null | undefined, now = new Date()): string {
  if (v == null) return DASH;
  const d = toDate(v);
  return dateIST.format(d) === dateIST.format(now) ? fmtTimeIST(d) : fmtDateTimeIST(d);
}

export function fmtAgo(v: string | number | Date | null | undefined, now = Date.now()): string {
  if (v == null) return DASH;
  const s = Math.max(0, Math.round((now - toDate(v).getTime()) / 1000));
  if (s < 60) return `${s}s ago`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 48) return `${h}h ago`;
  return `${Math.round(h / 24)}d ago`;
}
