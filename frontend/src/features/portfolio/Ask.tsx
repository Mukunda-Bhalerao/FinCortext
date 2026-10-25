import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { ErrorState, Panel } from "../../components/ui/primitives";
import { api } from "../../lib/api";
import type { AIStatus, AskAnswer, Scenario } from "../../lib/types";
import { FactList } from "./Brief";

const SUGGESTED = [
  "Why does my largest stock get the most weight?",
  "What is the biggest risk in this portfolio?",
  "How did it hold up in the COVID crash?",
  "What if I drop my weakest stock and add the best diversifier?",
  "How much do costs and taxes take each year?",
];

interface Turn {
  question: string;
  answer?: AskAnswer;
  error?: unknown;
}

export function AskPanel({ ai, onScenario }: { ai: AIStatus; onScenario: (s: Scenario) => void }) {
  const [text, setText] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const ask = useMutation({
    mutationFn: (q: string) =>
      api.ask(
        q,
        turns
          .filter((t) => t.answer)
          .slice(-2)
          .flatMap((t) => [
            { role: "user" as const, content: t.question },
            { role: "assistant" as const, content: t.answer!.answer },
          ]),
      ),
    onSuccess: (answer, q) => setTurns((ts) => ts.map((t) => (t.question === q && !t.answer ? { ...t, answer } : t))),
    onError: (error, q) => setTurns((ts) => ts.map((t) => (t.question === q && !t.answer ? { ...t, error } : t))),
  });
  const submit = (q: string) => {
    const question = q.trim();
    if (question.length < 2 || ask.isPending) return;
    setTurns((ts) => [...ts, { question }].slice(-6));
    setText("");
    ask.mutate(question);
  };

  return (
    <Panel
      title="Ask about your portfolio"
      meta={ai.enabled ? `Answers cite the facts they use · ${ai.model}` : undefined}
    >
      {!ai.enabled ? (
        <p className="p-3.5 text-xs leading-relaxed text-muted">
          The assistant is off. {ai.detail} Everything else on this page works without it.
        </p>
      ) : (
        <div className="flex flex-col gap-3 p-3.5">
          {turns.length === 0 && (
            <div className="flex flex-wrap gap-1.5">
              {SUGGESTED.map((s) => (
                <button
                  key={s}
                  onClick={() => submit(s)}
                  className="rounded-full border border-line px-2.5 py-1 text-2xs text-muted hover:border-accent hover:text-accent"
                >
                  {s}
                </button>
              ))}
            </div>
          )}
          {turns.map((t, i) => (
            <div key={i} className="fc-rise space-y-1.5">
              <p className="text-xs font-medium text-fg">{t.question}</p>
              {t.error ? (
                <ErrorState error={t.error} compact />
              ) : !t.answer ? (
                <p className="fc-pulse text-xs text-faint">Checking the facts…</p>
              ) : (
                <div className="rounded-md border border-line bg-surface-2 p-2.5">
                  <p className="text-sm leading-relaxed whitespace-pre-line text-muted">{t.answer.answer}</p>
                  {t.answer.scenario && (
                    <button
                      onClick={() => onScenario(t.answer!.scenario!)}
                      className="mt-2 rounded-md border border-accent/50 px-2 py-1 text-2xs font-medium text-accent hover:bg-accent-soft"
                    >
                      Try it in the plan: {t.answer.scenario.label ?? "scenario"}
                    </button>
                  )}
                  {t.answer.cited.length > 0 && (
                    <details className="mt-2 border-t border-line pt-2">
                      <summary className="cursor-pointer text-2xs text-faint hover:text-fg">
                        {t.answer.grounded ? `Based on ${t.answer.cited.length} facts` : "Closest facts"}
                      </summary>
                      <div className="mt-2">
                        <FactList facts={t.answer.cited} />
                      </div>
                    </details>
                  )}
                </div>
              )}
            </div>
          ))}
          <form
            onSubmit={(e) => {
              e.preventDefault();
              submit(text);
            }}
            className="flex gap-2"
          >
            <input
              value={text}
              onChange={(e) => setText(e.target.value)}
              maxLength={500}
              placeholder="Ask why, compare options, or try a what-if…"
              className="h-8 min-w-0 flex-1 rounded-md border border-line bg-surface-2 px-2.5 text-sm text-fg outline-none placeholder:text-faint focus:border-accent"
              aria-label="Question"
            />
            <button
              type="submit"
              disabled={ask.isPending || text.trim().length < 2}
              className="rounded-md bg-accent px-3 text-xs font-medium text-white disabled:opacity-40"
            >
              Ask
            </button>
          </form>
          <p className="text-2xs text-faint">
            Answers use only numbers the engine computed; anything else is rejected. Not investment advice.
          </p>
        </div>
      )}
    </Panel>
  );
}
