import "@fontsource-variable/inter";
import "./styles/index.css";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { App } from "./app/App";
import { ApiError } from "./lib/api";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 10_000,
      refetchOnWindowFocus: false,
      retry: (count, err) => {
        if (err instanceof ApiError && (err.needsConnection || err.status === 404 || err.status === 400)) {
          return false;
        }
        return count < 2;
      },
    },
  },
});
if (import.meta.env.DEV) {
  // Test hook (development builds only).
  (window as unknown as { __fcQuery?: QueryClient }).__fcQuery = queryClient;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
