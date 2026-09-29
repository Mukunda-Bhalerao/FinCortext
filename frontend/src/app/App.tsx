import { useEffect, useState } from 'react';
import { Routes, Route, NavLink, Navigate } from 'react-router-dom';
import FinCortextLogo from '../utils/FinCortextLogo.png';
import { FinCortextProvider, useFinCortext } from './FinCortextContext';
import CompanySelector from '../components/common/CompanySelector';
import StatusBadge from '../components/common/StatusBadge';
import { describeFreshness } from '../features/company/useMarketQuote';
import DashboardPage from '../features/dashboard/DashboardPage';
import CompanyAnalysisPage from '../features/company/CompanyAnalysisPage';
import DataSourcesPage from '../features/data/DataSourcesPage';
import DataPipelinePage from '../features/data/DataPipelinePage';
import MarketDataPage from '../features/data/MarketDataPage';
import FilingImportPage from '../features/data/FilingImportPage';
import DataQualityPage from '../features/data/DataQualityPage';
import FirmAnalystPage from '../features/agents/FirmAnalystPage';
import IndustryAnalystPage from '../features/agents/IndustryAnalystPage';
import MacroAnalystPage from '../features/agents/MacroAnalystPage';
import SentimentAnalystPage from '../features/agents/SentimentAnalystPage';
import IntelligenceSummaryPage from '../features/agents/IntelligenceSummaryPage';
import PortfolioSynthesisPage from '../features/portfolio/PortfolioSynthesisPage';
import RoadmapPage from '../features/roadmap/RoadmapPage';
import PlaceholderPage from '../components/common/PlaceholderPage';

interface NavItem {
  to: string;
  label: string;
  end?: boolean;
  icon: JSX.Element;
}

const iconProps = {
  viewBox: '0 0 16 16',
  width: 15,
  height: 15,
  'aria-hidden': true,
} as const;

/** Product navigation — the six demo destinations. Internal data tooling
 *  stays reachable by URL but out of the demo UI. */
const NAV_ITEMS: NavItem[] = [
  {
    to: '/',
    label: 'Dashboard',
    end: true,
    icon: (
      <svg {...iconProps}>
        <rect x="1.5" y="1.5" width="5" height="5" rx="1" fill="none" stroke="currentColor" strokeWidth="1.4" />
        <rect x="9.5" y="1.5" width="5" height="5" rx="1" fill="none" stroke="currentColor" strokeWidth="1.4" />
        <rect x="1.5" y="9.5" width="5" height="5" rx="1" fill="none" stroke="currentColor" strokeWidth="1.4" />
        <rect x="9.5" y="9.5" width="5" height="5" rx="1" fill="none" stroke="currentColor" strokeWidth="1.4" />
      </svg>
    ),
  },
  {
    to: '/company',
    label: 'Company Analysis',
    icon: (
      <svg {...iconProps}>
        <rect x="2.5" y="5" width="11" height="9" rx="1" fill="none" stroke="currentColor" strokeWidth="1.4" />
        <path d="M5.5 5V3.5h5V5M5.5 8h2M5.5 10.5h2M9.5 8h1M9.5 10.5h1" stroke="currentColor" strokeWidth="1.3" />
      </svg>
    ),
  },
  {
    to: '/intelligence/firm',
    label: 'Firm Analyst',
    icon: (
      <svg {...iconProps}>
        <path d="M2.5 13.5V8l3.5-4 3.5 4v5.5M9.5 13.5V9.5l4-2.5v6.5" fill="none" stroke="currentColor" strokeWidth="1.4" />
      </svg>
    ),
  },
  {
    to: '/intelligence/industry',
    label: 'Industry Analyst',
    icon: (
      <svg {...iconProps}>
        <circle cx="8" cy="8" r="5.5" fill="none" stroke="currentColor" strokeWidth="1.4" />
        <path d="M8 2.5v11M2.5 8h11" stroke="currentColor" strokeWidth="1.1" />
      </svg>
    ),
  },
  {
    to: '/intelligence/macro',
    label: 'Macro Analyst',
    icon: (
      <svg {...iconProps}>
        <path d="M2 13.5 6.5 9l3 3L14 6.5M9.5 6.5H14V11" fill="none" stroke="currentColor" strokeWidth="1.4" />
      </svg>
    ),
  },
  {
    to: '/intelligence/sentiment',
    label: 'Sentiment Analyst',
    icon: (
      <svg {...iconProps}>
        <path d="M2.5 3.5h11v7h-6l-3 2.5v-2.5h-2v-7z" fill="none" stroke="currentColor" strokeWidth="1.4" />
      </svg>
    ),
  },
  {
    to: '/intelligence/summary',
    label: 'Intelligence Summary',
    icon: (
      <svg {...iconProps}>
        <path d="M2.5 4.5h11M2.5 8h11M2.5 11.5h7" stroke="currentColor" strokeWidth="1.4" />
      </svg>
    ),
  },
  {
    to: '/portfolio',
    label: 'Portfolio Synthesis',
    icon: (
      <svg {...iconProps}>
        <path d="M2.5 13.5v-6l3.5 2 3.5-4 4 5.5" fill="none" stroke="currentColor" strokeWidth="1.4" />
      </svg>
    ),
  },
];

/** Right side of the topbar: real data freshness for the selected company.
 *  The timestamp is the actual Upstox quote timestamp when available — never
 *  the server startup time, never the page-load time, never manufactured. */
function FreshnessPill() {
  const { symbol, pricesOf, ensurePrices, quoteOf, ensureQuote } = useFinCortext();
  const series = pricesOf(symbol);
  const quote = quoteOf(symbol);
  // Warm the shared per-symbol caches so the pill is live on every page.
  useEffect(() => {
    ensurePrices(symbol).catch(() => undefined);
    ensureQuote(symbol).catch(() => undefined);
  }, [symbol, ensurePrices, ensureQuote]);
  if (series === undefined && quote === undefined) {
    return <span className="muted freshness-pill">Loading market data…</span>;
  }
  const fresh = describeFreshness(
    quote?.timestamp ?? series?.quote_timestamp,
    quote?.source ?? series?.quote_source,
    series?.latest_trade_date,
    series?.source,
  );
  if (fresh.status === 'UNAVAILABLE') {
    return <span className="muted freshness-pill">Market data unavailable</span>;
  }
  return (
    <span className="freshness-pill">
      <StatusBadge status={fresh.status} />
      {fresh.status === 'LIVE' && (
        <span className="live-dot" title="Current market data" aria-label="Current market data" />
      )}
      <span className="muted">
        {fresh.label}
      </span>
    </span>
  );
}

const SIDEBAR_STORAGE_KEY = 'fincortext:sidebar-collapsed';

function Shell() {
  const { symbol, setSymbol } = useFinCortext();
  const withSymbol = (to: string) =>
    symbol ? `${to}?symbol=${encodeURIComponent(symbol)}` : to;
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    try {
      return localStorage.getItem(SIDEBAR_STORAGE_KEY) === '1';
    } catch {
      return false;
    }
  });
  const toggleSidebar = () => {
    setCollapsed((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(SIDEBAR_STORAGE_KEY, next ? '1' : '0');
      } catch {
        /* storage unavailable — collapse state just won't persist */
      }
      return next;
    });
  };

  return (
    <div className="app-shell">
      <aside className={collapsed ? 'sidebar collapsed' : 'sidebar'}>
        <div className="brand">
          <img src={FinCortextLogo} alt="FinCortext logo" className="brand-logo" />
          <div className="brand-text">
            <h1>FinCortext</h1>
            <span className="brand-tagline">Investment Intelligence</span>
          </div>
          <button
            type="button"
            className="side-collapse-btn"
            onClick={toggleSidebar}
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            aria-expanded={!collapsed}
            title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
              {collapsed ? (
                <path d="M6 3.5 10.5 8 6 12.5" fill="none" stroke="currentColor" strokeWidth="1.6" />
              ) : (
                <path d="M10 3.5 5.5 8 10 12.5" fill="none" stroke="currentColor" strokeWidth="1.6" />
              )}
            </svg>
          </button>
        </div>
        <nav className="side-nav" aria-label="Main navigation">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={withSymbol(item.to)}
              end={item.end}
              title={item.label}
              className={({ isActive }) =>
                isActive ? 'nav-link active' : 'nav-link'
              }
            >
              <span className="nav-icon">{item.icon}</span>
              <span className="nav-label">{item.label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="side-foot">
          <span className="side-flow">Data → Intelligence → Decision</span>
          <span className="muted">FinCortext research</span>
        </div>
      </aside>
      <div className="shell-main">
        {/* NOTE: no `key` on <main> — keying by pathname used to remount every
            page on navigation, discarding the company selection and analysis
            results. Research state lives in FinCortextProvider instead. */}
        <header className="topbar">
          <CompanySelector value={symbol} onChange={setSymbol} />
          <FreshnessPill />
        </header>
        <main className="app-main">
          <Routes>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/company" element={<CompanyAnalysisPage />} />

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
            <Route path="/intelligence/macro" element={<MacroAnalystPage />} />
            <Route path="/intelligence/sentiment" element={<SentimentAnalystPage />} />
            <Route path="/intelligence/summary" element={<IntelligenceSummaryPage />} />
            {/* Roadmap — future-module skeletons only, no functionality */}
            <Route path="/roadmap" element={<RoadmapPage />} />

            {/* Portfolio — synthesis is implemented; risk/optimization stay future */}
            <Route path="/portfolio" element={<PortfolioSynthesisPage />} />
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
          <span>FinCortext — Investment Intelligence</span>
        </footer>
      </div>
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
