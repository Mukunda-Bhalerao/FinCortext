import { useSyncExternalStore } from "react";

export type ToastTone = "success" | "info" | "warning" | "error";

export interface Toast {
  id: number;
  title: string;
  body?: string;
  tone: ToastTone;
  ms: number;
}

let toasts: Toast[] = [];
let next = 1;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());

export function dismiss(id: number): void {
  toasts = toasts.filter((t) => t.id !== id);
  emit();
}

/** Show a short confirmation in the corner. Returns its id. */
export function toast(title: string, opts: { body?: string; tone?: ToastTone; ms?: number } = {}): number {
  const t: Toast = { id: next++, title, body: opts.body, tone: opts.tone ?? "success", ms: opts.ms ?? 4500 };
  toasts = [...toasts.slice(-3), t];
  emit();
  setTimeout(() => dismiss(t.id), t.ms);
  return t.id;
}

export function useToasts(): Toast[] {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => toasts,
  );
}
