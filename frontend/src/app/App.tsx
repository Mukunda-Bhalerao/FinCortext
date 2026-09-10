import { Routes, Route, NavLink, Navigate } from 'react-router-dom';
import FinCortextLogo from '../utils/FinCortextLogo.png';
import { FinCortextProvider, useFinCortext } from './FinCortextContext';
import DashboardPage from '../features/dashboard/DashboardPage';
import DataSourcesPage from '../features/data/DataSourcesPage';
import DataPipelinePage from '../features/data/DataPipelinePage';
import MarketDataPage from '../features/data/MarketDataPage';
import FilingImportPage from '../features/data/FilingImportPage';
import DataQualityPage from '../features/data/DataQualityPage';
import FirmAnalystPage from '../features/agents/FirmAnalystPage';
import IndustryAnalystPage from '../features/agents/IndustryAnalystPage';
import SentimentAnalystPage from '../features/agents/SentimentAnalystPage';
import IntelligenceSummaryPage from '../features/agents/IntelligenceSummaryPage';
import PlaceholderPage from '../components/common/PlaceholderPage';

interface NavItem {
  to: string;
  label: string;
  end?: boolean;
}

/** Product navigation — the five demo destinations. Internal data tooling
 *  stays reachable by URL but out of the demo path. */
const NAV_ITEMS: NavItem[] = [
  { to: '/', label: 'Dashboard', end: true },
  { to: '/intelligence/firm', label: 'Firm Analyst' },
  { to: '/intelligence/industry', label: 'Industry Analyst' },
  { to: '/intelligence/sentiment', label: 'Sentiment Analyst' },
  { to: '/intelligence/summary', label: 'Combined Summary' },
];

function Shell() {
  const { symbol } = useFinCortext();
  const withSymbol = (to: string) =>
    symbol ? `${to}?symbol=${encodeURIComponent(symbol)}` : to;

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand">
          <img src={FinCortextLogo} alt="FinCortext logo" className="brand-logo" />
          <div className="brand-text">
            <h1>FinCortext</h1>
            <span className="brand-tagline">Investment intelligence</span>
          </div>
        </div>
        <nav className="app-nav" aria-label="Main navigation">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={withSymbol(item.to)}
              end={item.end}
              className={({ isActive }) =>
                isActive ? 'nav-link active' : 'nav-link'
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </header>
      {/* NOTE: no `key` on <main> — keying by pathname used to remount every
          page on navigation, discarding the company selection and analysis
          results. Research state lives in FinCortextProvider instead. */}
      <main className="app-main">
        <Routes>
          <Route path="/" element={<DashboardPage />} />

          {/* Data tooling — internal routes, intentionally unlinked */}
          <Route path="/data/sources" element={<DataSourcesPage />} />
          <Route path="/data/pipeline" element={<DataPipelinePage />} />
          <Route path="/data/market" element={<MarketDataPage />} />
          <Route path="/data/filings" element={<FilingImportPage />} />
          <Route path="/data/quality" element={<DataQualityPage />} />
          <Route path="/data" element={<Navigate to="/data/sources" replace />} />

          {/* Intelligence */}
          <Route path="/intelligence/firm" element={<FirmAnalystPage />} />
          <Route path="/intelligence/industry" element={<IndustryAnalystPage />} />
          <Route path="/intelligence/sentiment" element={<SentimentAnalystPage />} />
          <Route path="/intelligence/summary" element={<IntelligenceSummaryPage />} />
          <Route
            path="/intelligence/macro"
            element={
              <PlaceholderPage
                title="Macro Analyst"
                note="Coming soon — macro-economic analysis is not implemented. It will join the standardized AgentOutput contract when built."
              />
            }
          />

          {/* Portfolio — future placeholders only */}
          <Route
            path="/portfolio"
            element={
              <PlaceholderPage
                title="Portfolio Agent"
                note="Reserved for the future Portfolio Agent. It will consume the standardized outputs of the implemented analysts — no portfolio recommendations or weights are generated today."
              />
            }
          />
          <Route
            path="/portfolio/risk"
            element={
              <PlaceholderPage
                title="Risk & Constraints"
                note="Future risk/constraint engine — not implemented."
              />
            }
          />
          <Route
            path="/portfolio/optimization"
            element={
              <PlaceholderPage
                title="Optimization"
                note="Future portfolio optimization — not implemented. No random or fake weights will ever be shown."
              />
            }
          />

          {/* Research — future placeholders only */}
          <Route
            path="/research/backtesting"
            element={
              <PlaceholderPage
                title="Backtesting"
                note="Future backtesting engine — not implemented. Point-in-time metadata is already preserved to support it later."
              />
            }
          />
          <Route
            path="/research/performance"
            element={
              <PlaceholderPage
                title="Performance"
                note="Future performance evaluation — not implemented."
              />
            }
          />
          <Route
            path="/research/experiments"
            element={
              <PlaceholderPage
                title="Experiments"
                note="Future experiment tracking — not implemented."
              />
            }
          />
          <Route path="/research" element={<Navigate to="/research/backtesting" replace />} />

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
      <footer className="app-footer">
        <span>FinCortext — investment intelligence research demo</span>
      </footer>
    </div>
  );
}

export default function App() {
  return (
    <FinCortextProvider>
      <Shell />
    </FinCortextProvider>
  );
}
