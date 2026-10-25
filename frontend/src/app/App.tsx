import { Route, Routes } from "react-router-dom";
import { EmptyState } from "../components/ui/primitives";
import { Dashboard } from "../features/dashboard/Dashboard";
import { MarketsPage } from "../features/markets/MarketsPage";
import { PortfolioPage } from "../features/portfolio/PortfolioPage";
import { ResearchPage } from "../features/research/ResearchPage";
import { StockPage } from "../features/stock/StockPage";
import { WatchlistPage } from "../features/watchlist/WatchlistPage";
import { Shell } from "./Shell";

export function App() {
  return (
    <Shell>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/markets" element={<MarketsPage />} />
        <Route path="/watchlist" element={<WatchlistPage />} />
        <Route path="/research" element={<ResearchPage />} />
        <Route path="/portfolio" element={<PortfolioPage />} />
        <Route path="/stock/:symbol" element={<StockPage />} />
        <Route path="*" element={<EmptyState title="Page not found" />} />
      </Routes>
    </Shell>
  );
}
