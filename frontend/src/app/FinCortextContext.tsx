import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { useSearchParams } from 'react-router-dom';
import { api } from '../services/api';
import type {
  AgentOutput,
  AgentOutputSummary,
  MarketStatusResponse,
  NewsListResponse,
  PriceSeriesResponse,
  UniverseEntry,
} from '../types/api';

const SYMBOL_STORAGE_KEY = 'fincortext:symbol';
const DEFAULT_SYMBOL = 'TCS';
const OUTPUTS_LIMIT = 30;
const NEWS_LIMIT = 5;

function initialSymbol(param: string | null): string {
  if (param) return param;
  try {
    return localStorage.getItem(SYMBOL_STORAGE_KEY) ?? DEFAULT_SYMBOL;
  } catch {
    return DEFAULT_SYMBOL;
  }
}

interface FinCortextContextValue {
  symbol: string;
  setSymbol: (next: string) => void;
  universe: UniverseEntry[] | null;
  universeError: string | null;
  entryFor: (s: string) => UniverseEntry | undefined;
  peersOf: (s: string) => UniverseEntry[];
  ensureUniverse: () => Promise<UniverseEntry[]>;
  pricesOf: (s: string) => PriceSeriesResponse | null | undefined;
  pricesErrorOf: (s: string) => string | null;
  ensurePrices: (s: string, refresh?: boolean) => Promise<PriceSeriesResponse | null>;
  outputsOf: (s: string) => AgentOutputSummary[] | null | undefined;
  outputsErrorOf: (s: string) => string | null;
  ensureOutputs: (s: string, refresh?: boolean) => Promise<AgentOutputSummary[]>;
  newsOf: (s: string) => NewsListResponse | null | undefined;
  newsErrorOf: (s: string) => string | null;
  ensureNews: (s: string, refresh?: boolean) => Promise<NewsListResponse | null>;
  invalidateNews: (s: string) => void;
  marketStatus: MarketStatusResponse | null;
  ensureMarketStatus: () => Promise<MarketStatusResponse | null>;
  runOf: (s: string, agentId: string) => AgentOutput | undefined;
  runErrorOf: (s: string, agentId: string) => string | undefined;
  recordRun: (s: string, agentId: string, output: AgentOutput) => void;
  recordRunError: (s: string, agentId: string, message: string) => void;
}

const FinCortextContext = createContext<FinCortextContextValue | null>(null);

/**
 * Session-wide research state.
 *
 * Why this exists: every demo page used to own its own copy of the selected
 * company and its fetched data, and the app shell remounted the whole page on
 * every route change — so Dashboard → analyst → Dashboard re-fetched
 * everything and discarded analysis results. This provider owns the company
 * selection (mirrored to `?symbol=` so links stay shareable) and caches
 * backend reads per symbol for the session. Navigating never refetches;
 * only an explicit fresh analysis or refresh writes new data.
 *
 * Cheap backend reads are cached, never re-run: expensive agent runs live in
 * `runCache` and are recorded into the outputs history cache, so returning to
 * a page shows the previous result instantly with its timestamp instead of
 * re-running the model pipeline.
 */
export function FinCortextProvider({ children }: { children: ReactNode }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const paramSymbol = searchParams.get('symbol');
  const [symbolOverride, setSymbolOverride] = useState<string | null>(null);
  const symbol = paramSymbol ?? symbolOverride ?? initialSymbol(null);

  const [universe, setUniverse] = useState<UniverseEntry[] | null>(null);
  const [universeError, setUniverseError] = useState<string | null>(null);
  const [prices, setPrices] = useState<Record<string, PriceSeriesResponse | null>>({});
  const [pricesError, setPricesError] = useState<Record<string, string | null>>({});
  const [outputs, setOutputs] = useState<Record<string, AgentOutputSummary[] | null>>({});
  const [outputsError, setOutputsError] = useState<Record<string, string | null>>({});
  const [news, setNews] = useState<Record<string, NewsListResponse | null>>({});
  const [newsError, setNewsError] = useState<Record<string, string | null>>({});
  const [marketStatus, setMarketStatus] = useState<MarketStatusResponse | null>(null);
  const [runs, setRuns] = useState<Record<string, AgentOutput>>({});
  const [runErrors, setRunErrors] = useState<Record<string, string>>({});
  const inflight = useRef<Record<string, Promise<unknown>>>({});
  // Ref mirrors of the caches below. The `ensure*` callbacks consult these
  // instead of closing over state: a stale closure after rapid symbol
  // switches must never issue a duplicate fetch for settled data.
  const pricesCache = useRef<Record<string, PriceSeriesResponse | null>>({});
  const outputsCache = useRef<Record<string, AgentOutputSummary[] | null>>({});
  const newsCache = useRef<Record<string, NewsListResponse | null>>({});

  const once = useCallback(<T,>(key: string, fn: () => Promise<T>): Promise<T> => {
    const existing = inflight.current[key];
    if (existing) return existing as Promise<T>;
    const p = fn().finally(() => {
      delete inflight.current[key];
    });
    inflight.current[key] = p;
    return p;
  }, []);

  const setSymbol = useCallback(
    (next: string) => {
      if (!next) return;
      setSymbolOverride(next);
      setSearchParams(next ? { symbol: next } : {}, { replace: true });
      try {
        localStorage.setItem(SYMBOL_STORAGE_KEY, next);
      } catch {
        /* storage unavailable — URL still carries the symbol */
      }
    },
    [setSearchParams],
  );

  const ensureUniverse = useCallback(async (): Promise<UniverseEntry[]> => {
    return once('universe', async () => {
      try {
        const r = await api.universe();
        setUniverse(r.entries);
        setUniverseError(null);
        return r.entries;
      } catch (e) {
        setUniverseError(e instanceof Error ? e.message : String(e));
        throw e;
      }
    });
  }, [once]);

  useEffect(() => {
    ensureUniverse().catch(() => {
      /* error state is exposed via universeError */
    });
  }, [ensureUniverse]);

  const entryFor = useCallback(
    (s: string) => universe?.find((e) => e.symbol === s),
    [universe],
  );

  const peersOf = useCallback(
    (s: string) => {
      const entry = universe?.find((e) => e.symbol === s);
      if (!entry) return [];
      return universe?.filter((e) => e.sector === entry.sector) ?? [];
    },
    [universe],
  );

  const ensurePrices = useCallback(
    (s: string, refresh = false): Promise<PriceSeriesResponse | null> => {
      if (!refresh && s in pricesCache.current)
        return Promise.resolve(pricesCache.current[s] ?? null);
      return once(`prices:${s}`, async () => {
        try {
          const series = await api.market.prices(s);
          pricesCache.current = { ...pricesCache.current, [s]: series };
          setPrices((prev) => ({ ...prev, [s]: series }));
          setPricesError((prev) => ({ ...prev, [s]: null }));
          return series;
        } catch (e) {
          const message = e instanceof Error ? e.message : String(e);
          if (!(s in pricesCache.current)) {
            pricesCache.current = { ...pricesCache.current, [s]: null };
            setPrices((prev) => (s in prev ? prev : { ...prev, [s]: null }));
          }
          setPricesError((prev) => ({ ...prev, [s]: message }));
          return null;
        }
      });
    },
    [once],
  );

  const ensureOutputs = useCallback(
    (s: string, refresh = false): Promise<AgentOutputSummary[]> => {
      if (!refresh && s in outputsCache.current)
        return Promise.resolve(outputsCache.current[s] ?? []);
      return once(`outputs:${s}`, async () => {
        try {
          const r = await api.agents.outputs(undefined, s, OUTPUTS_LIMIT);
          outputsCache.current = { ...outputsCache.current, [s]: r.outputs };
          setOutputs((prev) => ({ ...prev, [s]: r.outputs }));
          setOutputsError((prev) => ({ ...prev, [s]: null }));
          return r.outputs;
        } catch (e) {
          if (!(s in outputsCache.current)) {
            outputsCache.current = { ...outputsCache.current, [s]: [] };
            setOutputs((prev) => (s in prev ? prev : { ...prev, [s]: [] }));
          }
          setOutputsError((prev) => ({
            ...prev,
            [s]: e instanceof Error ? e.message : String(e),
          }));
          return [];
        }
      });
    },
    [once],
  );

  const ensureNews = useCallback(
    (s: string, refresh = false): Promise<NewsListResponse | null> => {
      if (!refresh && s in newsCache.current)
        return Promise.resolve(newsCache.current[s] ?? null);
      return once(`news:${s}`, async () => {
        try {
          const r = await api.news.list(s, NEWS_LIMIT);
          newsCache.current = { ...newsCache.current, [s]: r };
          setNews((prev) => ({ ...prev, [s]: r }));
          setNewsError((prev) => ({ ...prev, [s]: null }));
          return r;
        } catch (e) {
          if (!(s in newsCache.current)) {
            newsCache.current = { ...newsCache.current, [s]: null };
            setNews((prev) => (s in prev ? prev : { ...prev, [s]: null }));
          }
          setNewsError((prev) => ({
            ...prev,
            [s]: e instanceof Error ? e.message : String(e),
          }));
          return null;
        }
      });
    },
    [once],
  );

  const invalidateNews = useCallback((s: string) => {
    if (s in newsCache.current) {
      const next = { ...newsCache.current };
      delete next[s];
      newsCache.current = next;
    }
    setNews((prev) => {
      if (!(s in prev)) return prev;
      const next = { ...prev };
      delete next[s];
      return next;
    });
    setNewsError((prev) => {
      if (!(s in prev)) return prev;
      const next = { ...prev };
      delete next[s];
      return next;
    });
  }, []);

  const ensureMarketStatus = useCallback((): Promise<MarketStatusResponse | null> => {
    if (marketStatus) return Promise.resolve(marketStatus);
    return once('market-status', async () => {
      try {
        const r = await api.market.status();
        setMarketStatus(r);
        return r;
      } catch {
        return null;
      }
    });
  }, [once, marketStatus]);

  const runKey = (s: string, agentId: string) => `${s}:${agentId}`;

  const recordRun = useCallback((s: string, agentId: string, output: AgentOutput) => {
    setRuns((prev) => ({ ...prev, [runKey(s, agentId)]: output }));
    setRunErrors((prev) => {
      if (!(runKey(s, agentId) in prev)) return prev;
      const next = { ...prev };
      delete next[runKey(s, agentId)];
      return next;
    });
    // Fold the fresh result into the stored-history cache so the Dashboard
    // shows it immediately without refetching.
    const summary: AgentOutputSummary = {
      output_id: `${output.agent_id}:${output.entity_id}:${output.generated_at}`,
      agent_id: output.agent_id,
      entity_id: output.entity_id,
      score: output.score,
      signal: output.signal,
      confidence: output.confidence,
      rationale: output.rationale,
      generated_at: output.generated_at,
      data_version: output.data_version,
      status: output.status,
    };
    setOutputs((prev) => ({
      ...prev,
      [s]: [summary, ...(prev[s] ?? [])].slice(0, OUTPUTS_LIMIT),
    }));
    outputsCache.current = {
      ...outputsCache.current,
      [s]: [summary, ...(outputsCache.current[s] ?? [])].slice(0, OUTPUTS_LIMIT),
    };
  }, []);

  const recordRunError = useCallback((s: string, agentId: string, message: string) => {
    setRunErrors((prev) => ({ ...prev, [runKey(s, agentId)]: message }));
  }, []);

  const value = useMemo<FinCortextContextValue>(
    () => ({
      symbol,
      setSymbol,
      universe,
      universeError,
      entryFor,
      peersOf,
      ensureUniverse,
      pricesOf: (s) => (s in prices ? prices[s] : undefined),
      pricesErrorOf: (s) => pricesError[s] ?? null,
      ensurePrices,
      outputsOf: (s) => (s in outputs ? outputs[s] : undefined),
      outputsErrorOf: (s) => outputsError[s] ?? null,
      ensureOutputs,
      newsOf: (s) => (s in news ? news[s] : undefined),
      newsErrorOf: (s) => newsError[s] ?? null,
      ensureNews,
      invalidateNews,
      marketStatus,
      ensureMarketStatus,
      runOf: (s, agentId) => runs[runKey(s, agentId)],
      runErrorOf: (s, agentId) => runErrors[runKey(s, agentId)],
      recordRun,
      recordRunError,
    }),
    [
      symbol,
      setSymbol,
      universe,
      universeError,
      entryFor,
      peersOf,
      ensureUniverse,
      prices,
      pricesError,
      ensurePrices,
      outputs,
      outputsError,
      ensureOutputs,
      news,
      newsError,
      ensureNews,
      invalidateNews,
      marketStatus,
      ensureMarketStatus,
      runs,
      runErrors,
      recordRun,
      recordRunError,
    ],
  );

  return <FinCortextContext.Provider value={value}>{children}</FinCortextContext.Provider>;
}

export function useFinCortext(): FinCortextContextValue {
  const ctx = useContext(FinCortextContext);
  if (!ctx) throw new Error('useFinCortext must be used inside <FinCortextProvider>');
  return ctx;
}
