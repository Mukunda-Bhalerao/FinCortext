import { useMutation } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ErrorState, Panel } from "../../components/ui/primitives";
import { api } from "../../lib/api";
import type { AIStatus, AskAnswer, Scenario } from "../../lib/types";
import { FactList } from "./Brief";
import { ToolResult } from "./ToolResult";

const SUGGESTED = [
  "Why is my weakest stock lagging?",
  "Compare the objectives",
  "What if I add the best diversifier?",
  "Can I reach 50 lakh in 10 years adding 10k a month?",
  "What is the biggest risk in this portfolio?",
];

interface Turn {
  question: string;
  answer?: AskAnswer;
  error?: unknown;
}

export function AskPanel({
  ai,
  onScenario,
  suggestions,
}: {
  ai: AIStatus;
  onScenario: (s: Scenario) => void;
  suggestions?: string[];
}) {
  const chips = suggestions?.length ? suggestions : SUGGESTED;
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

  // An alert's "Ask about this" arrives as ?ask=...; ask it once, then clear the parameter.
  const [params, setParams] = useSearchParams();
  const asked = useRef(false);
  const incoming = params.get("ask");
  useEffect(() => {
    if (!incoming || asked.current) return;
    asked.current = true;
    submit(incoming.slice(0, 500));
    params.delete("ask");
    setParams(params, { replace: true });
  }, [incoming]);

  return (
    <Panel
      title="Portfolio analyst"
      meta={
        ai.enabled
          ? `Explained by ${ai.model} · ${ai.calls_today}/${ai.daily_limit} model calls today`
          : "Language model off: answers come from the calculation engine"
      }
    >
      {
        <div className="flex flex-col gap-3 p-3.5">
          {turns.length === 0 && (
            <div className="flex flex-wrap gap-1.5">
              {chips.map((s) => (
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
                  {t.answer.answered_by === "engine" && (
                    <p className="mt-1 text-2xs text-faint">
                      Answered by the calculation engine{t.answer.notice ? `: ${t.answer.notice}` : "."}
                    </p>
                  )}
                  <ToolResult answer={t.answer} />
                  {t.answer.scenario && (
                    <button
                      onClick={() => onScenario(t.answer!.scenario!)}
                      className="mt-2 rounded-md border border-accent/50 px-2 py-1 text-2xs font-medium text-accent hover:bg-accent-soft"
                    >
                      Apply to my plan: {t.answer.scenario.label ?? "scenario"}
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
            Ask why a stock lagged, try adding, dropping or re-weighting stocks, compare objectives or check a goal.
            Calculations are done by the engine; the model only explains them, and answers with numbers it cannot back
            are rejected. Not investment advice.
          </p>
        </div>
      }
    </Panel>
  );
}
