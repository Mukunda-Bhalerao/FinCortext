import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { IconClose } from "../../components/ui/icons";
import { cx } from "../../components/ui/primitives";
import { api } from "../../lib/api";
import type { ChatAnswer, Fact } from "../../lib/types";
import { AnswerCard } from "./Cards";

interface Message {
  role: "user" | "assistant";
  content: string;
  answer?: ChatAnswer;
}

const BASIS_HINT: Record<string, string> = {
  measured: "calculated from real data",
  observed: "taken from a source as it stands",
  estimate: "an estimate, stated as one",
  replay: "replayed over past data",
};

function Sources({ facts }: { facts: Fact[] }) {
  const [open, setOpen] = useState(false);
  if (!facts.length) return null;
  return (
    <div className="mt-2">
      <button onClick={() => setOpen((v) => !v)} aria-expanded={open} className="text-2xs text-faint hover:text-fg">
        {open ? "Hide" : "Show"} what this rests on ({facts.length})
      </button>
      {open && (
        <ul className="mt-1.5 space-y-1.5 border-l-2 border-line pl-2.5">
          {facts.map((f) => (
            <li key={f.id} className="text-2xs leading-relaxed text-muted">
              {f.text}
              <span className="text-faint">
                {" "}
                — {f.source}
                {BASIS_HINT[f.basis] ? `, ${BASIS_HINT[f.basis]}` : ""}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Bubble({ m, onAsk }: { m: Message; onAsk: (q: string) => void }) {
  if (m.role === "user")
    return (
      <div className="flex justify-end">
        <p className="max-w-[85%] rounded-xl rounded-br-sm bg-accent px-3 py-2 text-xs text-white">{m.content}</p>
      </div>
    );
  const a = m.answer;
  return (
    <div className="flex flex-col gap-2">
      <p className="text-sm leading-relaxed whitespace-pre-line text-fg">{m.content}</p>
      {a?.cards.map((c, i) => (
        <AnswerCard key={i} card={c} />
      ))}
      {a?.notice && <p className="text-2xs leading-relaxed text-caution">{a.notice}</p>}
      {a && <Sources facts={a.facts} />}
      {a && (a.actions.length > 0 || a.follow_ups.length > 0) && (
        <div className="flex flex-wrap gap-1.5 pt-0.5">
          {a.actions.map((x) => (
            <Link
              key={x.to}
              to={x.to}
              className="rounded-full bg-accent-soft px-2.5 py-1 text-2xs font-medium text-accent hover:brightness-110"
            >
              {x.label} →
            </Link>
          ))}
          {a.follow_ups.map((q) => (
            <button
              key={q}
              onClick={() => onAsk(q)}
              className="rounded-full border border-line px-2.5 py-1 text-2xs text-muted hover:border-accent/60 hover:text-fg"
            >
              {q}
            </button>
          ))}
        </div>
      )}
      {a && (
        <p className="text-2xs text-faint">
          {a.answered_by === "model"
            ? `Worded by ${a.model} from the figures above; any number it invents is rejected.`
            : "Calculated by FinCortext from the data shown."}
        </p>
      )}
    </div>
  );
}

/** The assistant drawer: available on every page, answering from the app's own data. */
export function AssistantPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const location = useLocation();
  const params = useParams();
  const [messages, setMessages] = useState<Message[]>([]);
  const [text, setText] = useState("");
  const [focus, setFocus] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // The page the user is on, so "it" and "my account" mean something.
  const path = location.pathname;
  const symbol = focus ?? (path.startsWith("/stock/") ? decodeURIComponent(path.split("/")[2] ?? "") : null);
  const portfolioId = path.startsWith("/portfolios/") ? (params.id ?? null) : null;

  const starters = useQuery({
    queryKey: ["chat-starters", path, symbol],
    queryFn: () => api.chatStarters(path, symbol),
    enabled: open,
    staleTime: 5 * 60_000,
  });

  const ask = useMutation({
    mutationFn: (question: string) =>
      api.chat({
        question,
        history: messages.slice(-6).map((m) => ({ role: m.role, content: m.content.slice(0, 2000) })),
        context: { path, symbol, portfolio_id: portfolioId },
      }),
    onSuccess: (a) => {
      setMessages((m) => [...m, { role: "assistant", content: a.answer, answer: a }]);
      if (a.symbol) setFocus(a.symbol);
    },
    onError: (e) => {
      setMessages((m) => [...m, { role: "assistant", content: (e as Error).message }]);
    },
  });

  const send = (q: string) => {
    const question = q.trim();
    if (!question || ask.isPending) return;
    setMessages((m) => [...m, { role: "user", content: question }]);
    setText("");
    ask.mutate(question);
  };

  useEffect(() => {
    if (open) {
      endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
      inputRef.current?.focus();
    }
  }, [open, messages, ask.isPending]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  return (
    <>
      {open && <div className="fixed inset-0 z-40 bg-overlay lg:hidden" onClick={onClose} aria-hidden />}
      <aside
        aria-label="Assistant"
        aria-hidden={!open}
        className={cx(
          "fixed inset-y-0 right-0 z-40 flex w-[min(420px,100vw)] flex-col border-l border-line bg-surface shadow-2xl transition-transform duration-200",
          open ? "translate-x-0" : "pointer-events-none translate-x-full",
        )}
      >
        <header className="flex h-[var(--topbar-h)] shrink-0 items-center gap-2 border-b border-line px-3">
          <span className="flex h-6 w-6 items-center justify-center rounded-md bg-accent-soft text-accent" aria-hidden>
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M12 3l1.9 4.6L18.5 9l-4.6 1.9L12 15.5l-1.9-4.6L5.5 9l4.6-1.4z" />
              <path d="M18 15l.8 2.2L21 18l-2.2.8L18 21l-.8-2.2L15 18l2.2-.8z" />
            </svg>
          </span>
          <div className="min-w-0">
            <h2 className="text-sm font-semibold text-fg">Assistant</h2>
            <p className="truncate text-2xs text-faint">
              {symbol ? `Looking at ${symbol}` : "Answers from this app's own data"}
            </p>
          </div>
          <button
            onClick={onClose}
            className="ml-auto rounded p-1.5 text-muted hover:bg-surface-2 hover:text-fg"
            aria-label="Close assistant"
          >
            <IconClose />
          </button>
        </header>

        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-3">
          {messages.length === 0 && (
            <div className="space-y-3">
              <p className="text-sm leading-relaxed text-muted">
                Ask about a stock, why something moved, what an order costs, your practice account, IPOs or any market
                term. Every answer shows the figures it rests on, and I never predict prices.
              </p>
              <div className="flex flex-col items-start gap-1.5">
                {(starters.data ?? []).map((q) => (
                  <button
                    key={q}
                    onClick={() => send(q)}
                    className="rounded-full border border-line px-3 py-1.5 text-left text-xs text-muted hover:border-accent/60 hover:text-fg"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}
          {messages.map((m, i) => (
            <Bubble key={i} m={m} onAsk={send} />
          ))}
          {ask.isPending && (
            <p className="flex items-center gap-2 text-xs text-faint">
              <span className="fc-pulse h-1.5 w-1.5 rounded-full bg-accent" />
              Working it out from the data…
            </p>
          )}
          <div ref={endRef} />
        </div>

        <form
          className="shrink-0 border-t border-line p-2.5"
          onSubmit={(e) => {
            e.preventDefault();
            send(text);
          }}
        >
          <div className="flex items-end gap-2">
            <textarea
              ref={inputRef}
              value={text}
              rows={1}
              maxLength={500}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send(text);
                }
              }}
              placeholder={symbol ? `Ask about ${symbol}…` : "Ask about a stock, a cost, your account…"}
              className="max-h-28 min-h-[34px] flex-1 resize-none rounded-lg border border-line bg-surface-2 px-2.5 py-2 text-xs text-fg placeholder:text-faint focus:border-accent focus:outline-none"
            />
            <button
              type="submit"
              disabled={!text.trim() || ask.isPending}
              className="h-[34px] rounded-lg bg-accent px-3 text-xs font-medium text-white disabled:opacity-40"
            >
              Ask
            </button>
          </div>
          {messages.length > 0 && (
            <button
              type="button"
              onClick={() => {
                setMessages([]);
                setFocus(null);
              }}
              className="mt-1.5 text-2xs text-faint hover:text-fg"
            >
              Clear conversation
            </button>
          )}
        </form>
      </aside>
    </>
  );
}
