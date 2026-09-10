/** Product roadmap — planned capabilities, explicitly NOT implemented.
 *
 * Every module below is a skeleton entry: a name, a one-line scope, and an
 * "Under Development" badge. No metrics, no charts, no recommendations, no
 * fake results — the page exists so future work slots into the existing
 * architecture (provider → pipeline → agents → AgentOutput) without
 * restructuring the frontend.
 */

const GROUPS: Array<{
  heading: string;
  items: Array<{ name: string; scope: string }>;
}> = [
  {
    heading: 'Portfolio & Optimization',
    items: [
      {
        name: 'Portfolio Construction',
        scope: 'Combine analyst outputs into candidate portfolios under explicit mandates.',
      },
      {
        name: 'Portfolio Optimization',
        scope: 'Deterministic weight optimization subject to risk and constraint engines.',
      },
      {
        name: 'Risk Analysis',
        scope: 'Exposure, concentration and drawdown analysis on stored history.',
      },
    ],
  },
  {
    heading: 'Evaluation',
    items: [
      {
        name: 'Backtesting',
        scope: 'Point-in-time evaluation of analyst signals against stored history.',
      },
      {
        name: 'Performance Attribution',
        scope: 'Attribute realized performance to factors, sectors and timing.',
      },
    ],
  },
  {
    heading: 'Asset Coverage',
    items: [
      {
        name: 'Mutual Fund Intelligence',
        scope: 'Holdings- and style-based analysis of Indian mutual funds.',
      },
      {
        name: 'ETF Intelligence',
        scope: 'Tracking quality, liquidity and premium/discount monitoring for ETFs.',
      },
      {
        name: 'Fixed Income',
        scope: 'Yield, duration and credit coverage for bonds and deposits.',
      },
      {
        name: 'Gold & Commodities',
        scope: 'Price and regime context for gold, silver, energy and metals.',
      },
      {
        name: 'REITs / InvITs',
        scope: 'Distribution yield and NAV analysis for listed trusts.',
      },
      {
        name: 'Multi-Asset',
        scope: 'Cross-asset allocation views once single-asset coverage exists.',
      },
    ],
  },
  {
    heading: 'Research',
    items: [
      {
        name: 'Evidence Lab',
        scope: 'Saved analyst runs, comparisons and reviewer-friendly evidence packs.',
      },
    ],
  },
];

export default function RoadmapPage() {
  return (
    <section className="page roadmap">
      <h2>Roadmap</h2>
      <p className="muted page-description">
        Planned FinCortext capabilities. Everything below is under development —
        selecting an item explains its scope; nothing here produces analysis yet.
      </p>
      {GROUPS.map((group) => (
        <section key={group.heading} aria-label={group.heading}>
          <h3 className="roadmap-heading">{group.heading}</h3>
          <div className="card-grid">
            {group.items.map((item) => (
              <article key={item.name} className="card roadmap-card">
                <div className="roadmap-title-row">
                  <h4>{item.name}</h4>
                  <span className="badge badge-coming-soon">Under Development</span>
                </div>
                <p className="muted">{item.scope}</p>
              </article>
            ))}
          </div>
        </section>
      ))}
    </section>
  );
}
