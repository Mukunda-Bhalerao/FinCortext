import { fmtNumber } from "../../lib/format";

export const DASH = "—";

export function pct(v: number | null | undefined, digits = 1, signed = false): string {
  if (v == null || !Number.isFinite(v)) return DASH;
  const s = fmtNumber(Math.abs(v * 100), digits);
  if (!signed) return `${v < 0 ? "−" : ""}${s}%`;
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${s}%`;
}

export function num(v: number | null | undefined, digits = 2): string {
  if (v == null || !Number.isFinite(v)) return DASH;
  return `${v < 0 ? "−" : ""}${fmtNumber(Math.abs(v), digits)}`;
}

/** ₹12.4 L, ₹3.1 Cr, ₹48,250 */
export function rupees(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return DASH;
  const a = Math.abs(v);
  const sign = v < 0 ? "−" : "";
  if (a >= 1e7) return `${sign}₹${fmtNumber(a / 1e7, 2)} Cr`;
  if (a >= 1e5) return `${sign}₹${fmtNumber(a / 1e5, 2)} L`;
  return `${sign}₹${fmtNumber(a, 0)}`;
}

export const SERIES = Array.from({ length: 8 }, (_, i) => `var(--series-${i + 1})`);
