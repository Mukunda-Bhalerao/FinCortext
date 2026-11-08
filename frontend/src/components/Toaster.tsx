import { dismiss, useToasts, type ToastTone } from "../lib/toast";
import { cx } from "./ui/primitives";

const TONE: Record<ToastTone, { bar: string; icon: string }> = {
  success: { bar: "bg-up", icon: "text-up" },
  info: { bar: "bg-accent", icon: "text-accent" },
  warning: { bar: "bg-caution", icon: "text-caution" },
  error: { bar: "bg-down", icon: "text-down" },
};

function Icon({ tone }: { tone: ToastTone }) {
  const path =
    tone === "success"
      ? "M5 12.5l4.5 4.5L19 7.5"
      : tone === "error"
        ? "M6 6l12 12M18 6L6 18"
        : tone === "warning"
          ? "M12 8v5M12 16.5v.5"
          : "M12 11v6M12 7.5v.5";
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d={path} />
    </svg>
  );
}

/** Corner notifications: confirmations of what just happened, gone on their own. */
export function Toaster() {
  const toasts = useToasts();
  return (
    <div
      className="pointer-events-none fixed right-3 bottom-3 z-50 flex w-[min(360px,calc(100vw-24px))] flex-col gap-2"
      role="status"
      aria-live="polite"
    >
      {toasts.map((t) => (
        <div
          key={t.id}
          className="fc-toast pointer-events-auto relative overflow-hidden rounded-lg border border-line-strong bg-surface shadow-xl"
        >
          <div className="flex gap-2.5 p-3 pr-8">
            <span className={cx("mt-0.5 shrink-0", TONE[t.tone].icon)}>
              <Icon tone={t.tone} />
            </span>
            <div className="min-w-0">
              <p className="text-sm font-medium text-fg">{t.title}</p>
              {t.body && <p className="mt-0.5 text-xs leading-relaxed text-muted">{t.body}</p>}
            </div>
          </div>
          <button
            onClick={() => dismiss(t.id)}
            className="absolute top-2 right-2 rounded p-1 text-faint hover:bg-surface-2 hover:text-fg"
            aria-label="Dismiss"
          >
            <svg
              width="12"
              height="12"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.2"
              strokeLinecap="round"
            >
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>
          <div
            className={cx("fc-toast-bar absolute bottom-0 left-0 h-0.5 w-full opacity-60", TONE[t.tone].bar)}
            style={{ animationDuration: `${t.ms}ms` }}
          />
        </div>
      ))}
    </div>
  );
}
