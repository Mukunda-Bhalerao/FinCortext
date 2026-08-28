import { Routes, Route, NavLink, Navigate } from 'react-router-dom';
import DashboardPage from '../features/dashboard/DashboardPage';
import PlaceholderPage from '../components/common/PlaceholderPage';

const nav = [
  { to: '/', label: 'Dashboard', end: true },
  { to: '/data', label: 'Data' },
  { to: '/intelligence/firm', label: 'Firm Analyst' },
  { to: '/intelligence/industry', label: 'Industry Analyst' },
  { to: '/intelligence/sentiment', label: 'Sentiment Analyst' },
  { to: '/intelligence/macro', label: 'Macro Analyst' },
  { to: '/portfolio', label: 'Portfolio' },
  { to: '/research', label: 'Research' },
];

export default function App() {
  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand">
          <span className="brand-mark">FC</span>
          <div>
            <h1>FinCortext</h1>
            <p>AI-Powered Investment Intelligence</p>
          </div>
        </div>
        <nav className="app-nav">
          {nav.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </header>
      <main className="app-main">
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/data" element={<PlaceholderPage title="Data" />} />
          <Route path="/intelligence/firm" element={<PlaceholderPage title="Firm Analyst" />} />
          <Route path="/intelligence/industry" element={<PlaceholderPage title="Industry Analyst" />} />
          <Route path="/intelligence/sentiment" element={<PlaceholderPage title="Sentiment Analyst" />} />
          <Route path="/intelligence/macro" element={<PlaceholderPage title="Macro Analyst" note="Coming soon — not implemented in V1." />} />
          <Route path="/portfolio" element={<PlaceholderPage title="Portfolio" note="Reserved for the future Portfolio Agent. Not implemented yet." />} />
          <Route path="/research" element={<PlaceholderPage title="Research" note="Backtesting, performance and experiments are not implemented yet." />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
      <footer className="app-footer">
        <span>FinCortext v0.1.0 — research MVP</span>
        <span>Portfolio synthesis is reserved for the future Portfolio Agent.</span>
      </footer>
    </div>
  );
}