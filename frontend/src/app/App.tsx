import { Route, Routes, useLocation } from "react-router-dom";
import { ErrorBoundary } from "../components/ErrorBoundary";
import { EmptyState } from "../components/ui/primitives";
import { Dashboard } from "../features/dashboard/Dashboard";
import { MarketsPage } from "../features/markets/MarketsPage";
import { PortfolioPage } from "../features/portfolio/PortfolioPage";
import { ResearchPage } from "../features/research/ResearchPage";
import { StatusPage } from "../features/status/StatusPage";
import { StockPage } from "../features/stock/StockPage";
import { WatchlistPage } from "../features/watchlist/WatchlistPage";
import { Shell } from "./Shell";

export function App() {
  const location = useLocation();
  return (
    <Shell>
      <ErrorBoundary resetKey={location.pathname}>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/markets" element={<MarketsPage />} />
          <Route path="/watchlist" element={<WatchlistPage />} />
          <Route path="/research" element={<ResearchPage />} />
          <Route path="/portfolio" element={<PortfolioPage />} />
          <Route path="/stock/:symbol" element={<StockPage />} />
          <Route path="/status" element={<StatusPage />} />
          <Route path="*" element={<EmptyState title="Page not found" />} />
        </Routes>
      </ErrorBoundary>
    </Shell>
  );
}
