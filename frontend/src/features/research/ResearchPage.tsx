import { Panel } from "../../components/ui/primitives";

export const MODULES = [
  {
    name: "Firm",
    scope: "Ratios, growth, margins, valuation against peers and technical indicators for a single company.",
    needs: "Fundamentals ingestion",
  },
  {
    name: "Industry",
    scope: "Sector index returns, peer percentile ranks and constituent breadth.",
    needs: "Peer mapping and sector constituents",
  },
  {
    name: "Macro",
    scope: "Rates, inflation, currency and institutional flows, with sector sensitivity.",
    needs: "RBI, MOSPI and FRED data pipelines",
  },
  {
    name: "Sentiment",
    scope: "Headline sentiment scored by a local model, aggregated per company and sector.",
    needs: "Local sentiment model",
  },
];

export function ResearchPage() {
  return (
    <div className="mx-auto flex max-w-[1200px] flex-col gap-3 p-3 sm:p-4">
      <div>
        <h1 className="text-lg font-semibold text-fg">Research</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted">
          Each research module will return a signal with the evidence behind it: metric, value, source and as-of time,
          plus a list of data gaps. No module is producing output yet, so nothing is shown here.
        </p>
      </div>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {MODULES.map((m) => (
          <Panel
            key={m.name}
            title={m.name}
            actions={<span className="text-2xs text-faint">Not yet available</span>}
          >
            <div className="space-y-2 px-3.5 py-3 text-sm">
              <p className="text-muted">{m.scope}</p>
              <p className="text-2xs text-faint">Requires: {m.needs}</p>
            </div>
          </Panel>
        ))}
      </div>
    </div>
  );
}
