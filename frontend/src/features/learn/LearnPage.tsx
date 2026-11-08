import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Panel, cx } from "../../components/ui/primitives";
import { GLOSSARY, type GlossaryEntry } from "../../lib/glossary";

const PATH: { title: string; text: string; to: string; cta: string }[] = [
  {
    title: "1. Watch the market",
    text: "Star a few companies you know. Open their charts and research to see how price, results and news connect.",
    to: "/watchlist",
    cta: "Open the watchlist",
  },
  {
    title: "2. Open a paper account",
    text: "Start with virtual cash. Every order shows the real charges and the price you need just to break even.",
    to: "/portfolios",
    cta: "Create a paper account",
  },
  {
    title: "3. Trade with a reason",
    text: "Write why you are buying and set a stop-loss before you buy. The journal will hold you to it.",
    to: "/portfolios",
    cta: "Go to your accounts",
  },
  {
    title: "4. Come back and review",
    text: "Each visit explains what moved your stocks: the market, the sector or the company itself.",
    to: "/portfolios",
    cta: "See what happened",
  },
  {
    title: "5. Test an idea properly",
    text: "Turn a hunch into rules, test it on years of real prices, and check that it still works on later years.",
    to: "/lab",
    cta: "Open the Strategy Lab",
  },
  {
    title: "6. Read your scorecard",
    text: "Win rate, charges, tax and how you did against simply holding the NIFTY 50. Habits show up here first.",
    to: "/portfolios",
    cta: "Check your scorecard",
  },
];

const GROUPS: GlossaryEntry["group"][] = [
  "Orders",
  "Costs and tax",
  "Markets",
  "Indicators",
  "IPOs",
  "Measuring results",
];

export function LearnPage() {
  const [q, setQ] = useState("");
  const [group, setGroup] = useState<GlossaryEntry["group"] | "All">("All");
  const entries = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return Object.values(GLOSSARY)
      .filter((e) => group === "All" || e.group === group)
      .filter((e) => !needle || e.term.toLowerCase().includes(needle) || e.text.toLowerCase().includes(needle))
      .sort((a, b) => a.term.localeCompare(b.term));
  }, [q, group]);

  return (
    <div className="mx-auto flex max-w-[1200px] flex-col gap-4 p-3 sm:p-4">
      <div>
        <h1 className="text-lg font-semibold text-fg">Learn</h1>
        <p className="text-xs text-muted">
          A path from watching your first stock to testing your own strategy, and the terms you will meet on the way.
          Underlined words across the app open these explanations too.
        </p>
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {PATH.map((s) => (
          <div key={s.title} className="flex flex-col gap-2 rounded-lg border border-line bg-surface p-4">
            <h2 className="text-sm font-semibold text-fg">{s.title}</h2>
            <p className="flex-1 text-xs leading-relaxed text-muted">{s.text}</p>
            <Link to={s.to} className="text-xs font-medium text-accent hover:underline">
              {s.cta} →
            </Link>
          </div>
        ))}
      </div>
      <Panel
        title="Glossary"
        meta={`${entries.length} terms`}
        actions={
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search terms"
            aria-label="Search terms"
            className="h-7 w-44 rounded-md border border-line bg-surface-2 px-2 text-xs text-fg placeholder:text-faint focus:border-accent focus:outline-none"
          />
        }
      >
        <div className="flex flex-wrap gap-1.5 border-b border-line px-3.5 py-2">
          {(["All", ...GROUPS] as const).map((g) => (
            <button
              key={g}
              onClick={() => setGroup(g)}
              className={cx(
                "rounded-full border px-2 py-0.5 text-2xs",
                group === g ? "border-accent bg-accent-soft text-fg" : "border-line text-muted hover:text-fg",
              )}
            >
              {g}
            </button>
          ))}
        </div>
        <dl className="grid grid-cols-1 divide-y divide-line md:grid-cols-2 md:divide-y-0">
          {entries.map((e) => (
            <div key={e.term} className="border-line px-3.5 py-2.5 md:border-b">
              <dt className="text-sm font-medium text-fg">
                {e.term} <span className="text-2xs font-normal text-faint">· {e.group}</span>
              </dt>
              <dd className="mt-0.5 text-xs leading-relaxed text-muted">{e.text}</dd>
            </div>
          ))}
        </dl>
      </Panel>
    </div>
  );
}
