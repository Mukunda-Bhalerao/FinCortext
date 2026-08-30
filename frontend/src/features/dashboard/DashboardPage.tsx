import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import CompanySelector from '../../components/common/CompanySelector';

const MODULES = [
  {
    to: '/intelligence/firm',
    title: 'Firm Analyst',
    description:
      'Company fundamentals and market behavior — profitability, growth, leverage, valuation and price momentum, scored from official filings and stored prices.',
  },
  {
    to: '/intelligence/industry',
    title: 'Industry Analyst',
    description:
      'Peer and sector context — environment momentum, relative strength and volatility regime, measured against the company\u2019s sector peers.',
  },
  {
    to: '/intelligence/sentiment',
    title: 'Sentiment Analyst',
    description:
      'Financial-news sentiment — recency-weighted aggregation of relevant stored articles, scored by a local financial-language model.',
  },
] as const;

/** Dashboard — clean product-oriented overview for the demo.
 *
 * Presents the three intelligence modules and routes the selected company
 * through the demo flow. No backend paths, configuration, cache or pipeline
 * diagnostics are shown (those endpoints remain available in the backend).
 */
export default function DashboardPage() {
  const [symbol, setSymbol] = useState('TCS');
  const navigate = useNavigate();

  const go = (to: string) => navigate(`${to}?symbol=${encodeURIComponent(symbol)}`);

  return (
    <section className="page">
      <h2>Investment Intelligence</h2>
      <p className="muted page-description">
        FinCortext is an AI-powered investment intelligence platform. It combines
        three independent perspectives on a company — fundamentals, industry
        context and financial-news sentiment — into transparent, explainable
        results. Every score ships with its evidence, methodology and honest
        data status: when required data is missing, the affected factor is
        reported as unavailable rather than fabricated.
      </p>

      <div className="run-bar">
        <CompanySelector value={symbol} onChange={setSymbol} />
        <button className="btn btn-primary" onClick={() => go('/intelligence/firm')}>
          Analyze Company
        </button>
      </div>

      <div className="card-grid">
        {MODULES.map((m) => (
          <div className="card" key={m.to}>
            <h3>{m.title}</h3>
            <p className="muted">{m.description}</p>
            <button className="btn" onClick={() => go(m.to)}>
              Open {m.title}
            </button>
          </div>
        ))}

        <div className="card">
          <h3>Combined Intelligence Summary</h3>
          <p className="muted">
            Run all three analysts for {symbol || 'the selected company'} and
            compare their standardized scores side by side, each with its own
            evidence and limitations.
          </p>
          <button className="btn" onClick={() => go('/intelligence/summary')}>
            Open Combined Summary
          </button>
        </div>
      </div>
    </section>
  );
}