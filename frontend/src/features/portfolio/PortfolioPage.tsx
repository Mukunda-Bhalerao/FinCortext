import { Panel } from "../../components/ui/primitives";

const PLANNED = [
  ["Holdings", "Enter positions and see them valued at live prices."],
  ["Allocation", "Breakdown by stock and sector."],
  ["Risk", "Volatility, Sharpe ratio, maximum drawdown and beta against NIFTY 50, computed from price history."],
  ["Model portfolio", "Constraint-based construction from research signals, with the rationale for each holding."],
];

export function PortfolioPage() {
  return (
    <div className="mx-auto flex max-w-[1200px] flex-col gap-3 p-3 sm:p-4">
      <div>
        <h1 className="text-lg font-semibold text-fg">Portfolio</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted">
          Portfolio tracking and analysis are not available yet. Metrics will only appear once holdings are entered and
          computed from real price history.
        </p>
      </div>
      <Panel title="Planned">
        <ul className="divide-y divide-line">
          {PLANNED.map(([name, text]) => (
            <li key={name} className="grid grid-cols-[140px_1fr] gap-3 px-3.5 py-2.5 text-sm">
              <span className="text-fg">{name}</span>
              <span className="text-muted">{text}</span>
            </li>
          ))}
        </ul>
      </Panel>
    </div>
  );
}
