"""Market data service: provider → validation → storage → provenance.

Orchestration layer used by API routes. Business logic lives here, not in
route handlers.

Upstox is the ONLY market provider (quotes + historical candles, verified
live): search resolves ANY valid NSE equity dynamically, quotes/history flow
through the same validation/storage/provenance pipeline, and analysts keep
consuming the normalized repository layer unchanged. Failures degrade
honestly to stored snapshots / explicit statuses — there is no fallback
provider. Pre-consolidation imports remain usable as `legacy_import` rows.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.core.config import settings
from app.core.exceptions import NotFoundError, ProviderError, ProviderUnavailableError
from app.core.logging import get_logger
from app.data.universe.universe_config import (
    build_dynamic_entry,
    get_universe,
    get_universe_entry,
    is_dynamic_symbol,
    register_dynamic_entry,
)
from app.data.validation.market_validation import validate_market_bars
from app.domain.contracts.providers import MarketDataProvider
from app.domain.models.base import DataStatus
from app.domain.models.market import MarketPrice
from app.repositories.market_repository import MarketRepository
from app.repositories.provenance_repository import ProvenanceRepository

logger = get_logger("services.market")


class MarketService:
    def __init__(
        self,
        provider: MarketDataProvider,
        market_repo: MarketRepository,
        provenance_repo: ProvenanceRepository,
        *,
        instrument_repo=None,
        universe_repo=None,
    ):
        self.provider = provider
        self.market_repo = market_repo
        self.provenance_repo = provenance_repo
        self.instrument_repo = instrument_repo
        self.universe_repo = universe_repo

    # -- dynamic resolution ---------------------------------------------------

    def _is_upstox_provider(self) -> bool:
        return (
            hasattr(self.provider, "resolve_equity")
            or hasattr(self.provider, "search_equity")
        )

    def _persist_dynamic(self, entry, meta: dict | None = None) -> None:
        register_dynamic_entry(entry)
        try:
            if self.universe_repo is not None:
                self.universe_repo.upsert_entry(entry)
        except Exception as exc:  # persistence must not break resolution
            logger.warning("Universe persist failed for %s: %s", entry.symbol, type(exc).__name__)
        try:
            if self.instrument_repo is not None and meta:
                self.instrument_repo.upsert(meta)
        except Exception as exc:
            logger.warning("Instrument cache failed for %s: %s", entry.symbol, type(exc).__name__)
        try:
            cache = getattr(self.provider, "cache_instrument", None)
            if callable(cache) and meta:
                cache(meta)
        except Exception:
            pass

    def _resolve_entry(self, symbol: str, instrument_key: str | None = None):
        """Resolve a company context, creating it dynamically via Upstox when valid.

        Static universe entries always win. Unknown symbols are resolved through
        the Upstox NSE-equity search (when the provider supports it) and cached
        for subsequent calls. Unknown symbols with no Upstox match raise
        NotFoundError so the API returns an honest 404.
        """
        raw = (symbol or "").strip()
        if not raw:
            raise NotFoundError("Empty symbol")
        # Explicit instrument key: trust it, build context around the symbol.
        key_hint = (instrument_key or "").strip() or None
        try:
            entry = get_universe_entry(raw)
            if key_hint and not getattr(entry, "instrument_key", None):
                try:
                    updated = entry.model_copy(update={"instrument_key": key_hint})
                    register_dynamic_entry(updated) if is_dynamic_symbol(updated.symbol) else None
                    # Static entries keep their config identity; just seed caches.
                    if self.instrument_repo is not None:
                        cached = self.instrument_repo.get_by_key(key_hint)
                        if cached is None:
                            self.instrument_repo.upsert(
                                {
                                    "instrument_key": key_hint,
                                    "symbol": updated.symbol,
                                    "trading_symbol": updated.symbol,
                                    "name": updated.name,
                                    "exchange": "NSE",
                                    "segment": "EQ",
                                }
                            )
                    cache = getattr(self.provider, "cache_instrument", None)
                    if callable(cache):
                        cache(
                            {
                                "instrument_key": key_hint,
                                "symbol": updated.symbol,
                                "trading_symbol": updated.symbol,
                                "name": updated.name,
                                "exchange": "NSE",
                                "segment": "EQ",
                            }
                        )
                except Exception:
                    pass
            return entry
        except NotFoundError:
            pass

        # Cached instrument metadata avoids re-searching on every call.
        if self.instrument_repo is not None:
            try:
                if key_hint:
                    cached = self.instrument_repo.get_by_key(key_hint)
                else:
                    cached = self.instrument_repo.get_by_symbol(raw.upper().replace(".NS", ""))
                if cached:
                    sym = str(cached.get("symbol") or "").upper()
                    if sym:
                        try:
                            return get_universe_entry(sym)
                        except NotFoundError:
                            pass
                        entry = build_dynamic_entry(
                            symbol=sym,
                            name=str(cached.get("name") or sym),
                            instrument_key=str(cached.get("instrument_key") or key_hint or ""),
                        )
                        self._persist_dynamic(entry, dict(cached))
                        # Seed provider resolver so history/quote skip search.
                        cache = getattr(self.provider, "cache_instrument", None)
                        if callable(cache):
                            cache(
                                {
                                    "instrument_key": entry.instrument_key or key_hint or "",
                                    "symbol": entry.symbol,
                                    "trading_symbol": sym,
                                    "name": entry.name,
                                    "exchange": "NSE",
                                    "segment": "EQ",
                                }
                            )
                        return entry
            except Exception:
                pass

        if not self._is_upstox_provider():
            raise NotFoundError(f"Symbol '{symbol}' is not in the configured universe")

        # Live resolution via Upstox NSE-equity search.
        try:
            if key_hint:
                # Key-first: fetch the quote to learn the trading symbol/name,
                # then register. Falls back to search when the quote fails.
                try:
                    quote_fn = getattr(self.provider, "fetch_quote_by_key", None)
                    if callable(quote_fn):
                        q = quote_fn(key_hint, symbol_hint=raw.upper())
                        sym = str(q.get("symbol") or raw).strip().upper()
                        entry = build_dynamic_entry(
                            symbol=sym,
                            name=str(q.get("trading_symbol") or sym),
                            instrument_key=key_hint,
                        )
                        meta = {
                            "instrument_key": key_hint,
                            "symbol": sym,
                            "trading_symbol": str(q.get("trading_symbol") or sym),
                            "name": entry.name,
                            "exchange": "NSE",
                            "segment": "EQ",
                        }
                        self._persist_dynamic(entry, meta)
                        return entry
                except (ProviderError, ProviderUnavailableError):
                    pass
            resolve_fn = getattr(self.provider, "resolve_equity", None)
            if not callable(resolve_fn):
                raise NotFoundError(f"Symbol '{symbol}' is not in the configured universe")
            meta = resolve_fn(raw)
            sym = str(meta.get("symbol") or raw).strip().upper()
            # A second lookup catches races where another request registered it.
            try:
                return get_universe_entry(sym)
            except NotFoundError:
                pass
            entry = build_dynamic_entry(
                symbol=sym,
                name=str(meta.get("name") or sym),
                instrument_key=str(meta.get("instrument_key") or key_hint or ""),
            )
            self._persist_dynamic(entry, meta)
            return entry
        except NotFoundError:
            raise
        except (ProviderError, ProviderUnavailableError) as exc:
            # "No NSE equity found" is an honest unknown symbol, not a 502.
            msg = getattr(exc, "message", "") or ""
            if "No NSE equity found" in msg:
                raise NotFoundError(f"Symbol '{symbol}' is not in the configured universe") from exc
            raise

    # -- search / resolve / quote ----------------------------------------------

    def search_symbols(self, query: str, *, records: int = 20) -> dict:
        """Dynamic stock search: Upstox NSE equities when available.

        Falls back to filtering the static universe when the wired provider
        has no search capability (fakes/tests) so the endpoint never 500s.
        """
        q = (query or "").strip()
        if not q:
            return {"query": query or "", "count": 0, "results": [], "source": self.provider.name}
        search_fn = getattr(self.provider, "search_equity", None)
        if callable(search_fn):
            try:
                results = search_fn(q, records=min(30, max(1, int(records or 20))))
            except (ProviderError, ProviderUnavailableError) as exc:
                raise
            # Cache every result so a subsequent select/quote avoids re-search.
            for meta in results:
                try:
                    if self.instrument_repo is not None:
                        self.instrument_repo.upsert(meta)
                    cache = getattr(self.provider, "cache_instrument", None)
                    if callable(cache):
                        cache(meta)
                except Exception:
                    continue
            return {
                "query": q,
                "count": len(results),
                "results": [
                    {
                        "symbol": r.get("symbol"),
                        "trading_symbol": r.get("trading_symbol"),
                        "name": r.get("name"),
                        "instrument_key": r.get("instrument_key"),
                        "exchange": r.get("exchange"),
                        "segment": r.get("segment"),
                        "isin": r.get("isin"),
                    }
                    for r in results
                ],
                "source": "upstox",
            }
        # Provider without search capability: local static-universe filter.
        ql = q.lower()
        matches = [
            e for e in get_universe()
            if ql in e.symbol.lower() or ql in e.name.lower()
        ]
        return {
            "query": q,
            "count": len(matches),
            "results": [
                {
                    "symbol": e.symbol,
                    "trading_symbol": e.symbol,
                    "name": e.name,
                    "instrument_key": getattr(e, "instrument_key", None),
                    "exchange": e.exchange,
                    "segment": "EQ",
                    "isin": None,
                }
                for e in matches
            ],
            "source": self.provider.name,
        }

    def resolve_symbol(self, symbol: str, instrument_key: str | None = None) -> dict:
        entry = self._resolve_entry(symbol, instrument_key)
        key = getattr(entry, "instrument_key", None)
        if not key and self.instrument_repo is not None:
            try:
                cached = self.instrument_repo.get_by_symbol(entry.symbol)
                if cached:
                    key = cached.get("instrument_key")
            except Exception:
                pass
        if not key:
            resolver_cache = getattr(self.provider, "_key_cache", {}) or {}
            key = resolver_cache.get(entry.symbol)
        return {
            "symbol": entry.symbol,
            "name": entry.name,
            "exchange": entry.exchange,
            "ticker": entry.ticker,
            "sector": entry.sector,
            "industry": entry.industry,
            "instrument_key": key,
            "dynamic": is_dynamic_symbol(entry.symbol),
            "source": self.provider.name,
        }

    def get_quote(self, symbol: str, instrument_key: str | None = None) -> dict:
        """Current market snapshot with explicit None for missing fields.

        Field names are snake_case and mirror the frontend Quote type exactly —
        this is the null-bug fix: valid Upstox values must never be lost to a
        rename between provider -> service -> API -> TypeScript.
        """
        entry = self._resolve_entry(symbol, instrument_key)
        key_hint = (instrument_key or "").strip() or getattr(entry, "instrument_key", None)
        if not key_hint and self.instrument_repo is not None:
            try:
                cached = self.instrument_repo.get_by_symbol(entry.symbol)
                if cached:
                    key_hint = cached.get("instrument_key")
            except Exception:
                pass
        quote_fn = getattr(self.provider, "fetch_quote_for_symbol", None)
        quote_by_key = getattr(self.provider, "fetch_quote_by_key", None)

        if callable(quote_fn) or callable(quote_by_key):
            try:
                if key_hint and callable(quote_by_key):
                    quote = quote_by_key(key_hint, symbol_hint=entry.symbol)
                elif callable(quote_fn):
                    quote = quote_fn(entry.symbol)
                else:
                    raise ProviderError("Quote provider unavailable.")
            except (ProviderError, ProviderUnavailableError) as exc:
                # Live quote failed: serve the last stored snapshot (CACHED)
                # so the UI keeps showing the latest valid market timestamp.
                stored = self.market_repo.get_stored_quote(entry.symbol)
                if stored and stored.get("last_price") is not None:
                    logger.warning(
                        "Live quote failed for %s (%s); serving stored snapshot",
                        entry.symbol, type(exc).__name__,
                    )
                    return self._stored_quote_response(entry, stored, live=False)
                raise
            # Enrich with company context; never overwrite real quote numbers.
            quote.setdefault("symbol", entry.symbol)
            quote.setdefault("name", entry.name)
            if not quote.get("instrument_key") and key_hint:
                quote["instrument_key"] = key_hint
            quote.setdefault("exchange", entry.exchange)
            quote.setdefault("segment", "EQ")
            quote["name"] = entry.name
            quote["symbol"] = entry.symbol
            has_price = quote.get("last_price") is not None
            quote["status"] = DataStatus.LIVE.value if has_price else DataStatus.UNAVAILABLE.value
            # Persist the key mapping once a live quote confirms it.
            if quote.get("instrument_key"):
                try:
                    if self.instrument_repo is not None:
                        self.instrument_repo.upsert(
                            {
                                "instrument_key": quote["instrument_key"],
                                "symbol": entry.symbol,
                                "trading_symbol": quote.get("trading_symbol") or entry.symbol,
                                "name": entry.name,
                                "exchange": "NSE",
                                "segment": "EQ",
                            }
                        )
                except Exception:
                    pass
            # Persist the live snapshot so the provider timestamp survives in
            # storage (newer-wins; legacy imports can never overwrite Upstox).
            try:
                self.market_repo.upsert_quote(quote)
            except Exception as exc:
                logger.warning(
                    "Quote snapshot store failed for %s: %s",
                    entry.symbol, type(exc).__name__,
                )
            quote["live"] = True
            return quote

        # Provider without live-quote capability: derive an honest snapshot
        # from stored bars.
        prices: list[MarketPrice] = self.market_repo.get_prices(entry.symbol)
        if not prices:
            return {
                "symbol": entry.symbol,
                "name": entry.name,
                "instrument_key": None,
                "trading_symbol": entry.symbol,
                "exchange": entry.exchange,
                "segment": "EQ",
                "source": self.provider.name,
                "status": DataStatus.UNAVAILABLE.value,
                "timestamp": None,
                "last_price": None,
                "prev_close": None,
                "open": None,
                "high": None,
                "low": None,
                "close": None,
                "volume": None,
                "average_price": None,
                "year_high": None,
                "year_low": None,
                "day_change": None,
                "day_change_pct": None,
                "live": False,
            }
        last = prices[-1]
        prev = prices[-2] if len(prices) > 1 else None
        highs = [p.high for p in prices]
        lows = [p.low for p in prices]
        enough_for_year = len(prices) >= 20
        day_change = (last.close - prev.close) if prev else None
        return {
            "symbol": entry.symbol,
            "name": entry.name,
            "instrument_key": None,
            "trading_symbol": entry.symbol,
            "exchange": entry.exchange,
            "segment": "EQ",
            "source": self.provider.name,
            "status": DataStatus.LIVE.value if (date.today() - last.trade_date).days <= 7 else DataStatus.CACHED.value,
            "timestamp": last.trade_date.isoformat(),
            "last_price": last.close,
            "prev_close": prev.close if prev else None,
            "open": last.open,
            "high": last.high,
            "low": last.low,
            "close": last.close,
            "volume": last.volume,
            "average_price": None,
            "year_high": max(highs) if enough_for_year else None,
            "year_low": min(lows) if enough_for_year else None,
            "day_change": day_change,
            "day_change_pct": ((day_change / prev.close) * 100.0) if (day_change is not None and prev and prev.close) else None,
            "live": False,
        }

    def _stored_quote_response(self, entry, stored: dict, *, live: bool) -> dict:
        """Shape a stored quote snapshot as a quote response (field-identical)."""
        return {
            "symbol": entry.symbol,
            "name": entry.name,
            "instrument_key": stored.get("instrument_key"),
            "trading_symbol": stored.get("trading_symbol") or entry.symbol,
            "exchange": stored.get("exchange") or entry.exchange,
            "segment": stored.get("segment") or "EQ",
            "source": stored.get("source"),
            "status": DataStatus.LIVE.value if live else DataStatus.CACHED.value,
            "timestamp": stored.get("timestamp"),
            "last_price": stored.get("last_price"),
            "prev_close": stored.get("prev_close"),
            "open": stored.get("open"),
            "high": stored.get("high"),
            "low": stored.get("low"),
            "close": stored.get("close"),
            "volume": stored.get("volume"),
            "average_price": stored.get("average_price"),
            "year_high": stored.get("year_high"),
            "year_low": stored.get("year_low"),
            "day_change": stored.get("day_change"),
            "day_change_pct": stored.get("day_change_pct"),
            "live": live,
        }

    # -- history ------------------------------------------------------------------

    def refresh_symbol(
        self,
        symbol: str,
        start: date | None = None,
        end: date | None = None,
        instrument_key: str | None = None,
    ) -> dict:
        """Fetch, validate, and store OHLCV for one symbol (static or dynamic)."""
        entry = self._resolve_entry(symbol, instrument_key)
        end = end or date.today()
        start = start or (end - timedelta(days=settings.market_history_days))

        # Canonical-key invariant: request the INTERNAL symbol. Providers
        # resolve their own tickers/keys; stored bars are keyed by it.
        key_hint = (instrument_key or "").strip() or getattr(entry, "instrument_key", None)
        if key_hint and hasattr(self.provider, "fetch_ohlcv_by_key"):
            try:
                bars = self.provider.fetch_ohlcv_by_key(entry.symbol, key_hint, start, end)
            except (ProviderError, ProviderUnavailableError):
                raise
        else:
            bars = self.provider.fetch_ohlcv(entry.symbol, start, end)
        validation = validate_market_bars(bars)

        written = 0
        if validation.valid:
            written = self.market_repo.upsert_bars(validation.valid)

        # Honest source: fallback bars carry their own provenance even when
        # the configured provider is Upstox.
        actual_source = self.provider.name
        try:
            if validation.valid and getattr(validation.valid[0], "source_name", None):
                actual_source = str(validation.valid[0].source_name)
        except Exception:
            pass

        self.provenance_repo.record(
            "market_refresh",
            entity_id=entry.symbol,
            source_type=actual_source,
            source_name=actual_source,
            rows_ingested=written,
            rows_rejected=len(validation.rejected),
            detail=str(validation.summary()["rejections"]) if validation.rejected else None,
        )
        logger.info(
            "Market refresh %s: %d stored, %d rejected",
            entry.symbol, written, len(validation.rejected),
        )
        return {
            "symbol": entry.symbol,
            "name": entry.name,
            "status": DataStatus.LIVE.value if written else DataStatus.UNAVAILABLE.value,
            "rows_stored": written,
            "rows_rejected": len(validation.rejected),
            "provider": actual_source,
            "instrument_key": key_hint or getattr(entry, "instrument_key", None),
            "start": start.isoformat(),
            "end": end.isoformat(),
        }

    def refresh_universe(self, symbols: list[str] | None = None) -> dict:
        """Refresh all (or selected) universe symbols; failures are isolated."""
        entries = get_universe()
        results = []
        for entry in entries:
            if symbols and entry.symbol not in {s.upper() for s in symbols}:
                continue
            try:
                results.append(self.refresh_symbol(entry.symbol))
            except ProviderError as exc:
                logger.error("Market refresh failed for %s: %s", entry.symbol, exc.message)
                results.append(
                    {
                        "symbol": entry.symbol,
                        "status": DataStatus.ERROR.value,
                        "error": exc.message,
                    }
                )
        stored = sum(1 for r in results if r.get("status") == DataStatus.LIVE.value)
        return {
            "provider": self.provider.name,
            "symbols_requested": len(results),
            "symbols_ok": stored,
            "results": results,
        }

    def ensure_history(
        self,
        symbols: list[str],
        *,
        min_bars: int,
        max_age_days: int = 7,
    ) -> list[dict]:
        """Ensure cached OHLCV coverage for `symbols`, fetching only what is missing.

        Used by agent orchestration (e.g. Industry Analyst data preparation):
        a symbol is sufficient when at least `min_bars` rows are stored AND
        the latest stored trade date is within `max_age_days` of today
        (mirrors the LIVE window of get_price_series, tolerant of weekends
        and holidays). Sufficient symbols are served from cache — the
        provider is NOT called. Insufficient or stale symbols go through the
        normal refresh pipeline (provider -> validation -> storage ->
        provenance). Provider failures are isolated per symbol and reported;
        this method never raises so agent runs can proceed with whatever
        cached data exists (honest limitation reporting downstream).
        """
        prepared: list[dict] = []
        for raw in symbols:
            try:
                entry = self._resolve_entry(raw)
            except NotFoundError as exc:
                prepared.append(
                    {
                        "symbol": (raw or "").strip().upper(),
                        "action": "refresh_failed",
                        "status": DataStatus.ERROR.value,
                        "error": exc.message,
                    }
                )
                continue
            rows = self.market_repo.count(entry.symbol)
            latest = self.market_repo.latest_trade_date(entry.symbol)
            fresh = latest is not None and (date.today() - latest).days <= max_age_days
            if rows >= min_bars and fresh:
                prepared.append(
                    {
                        "symbol": entry.symbol,
                        "action": "cached",
                        "rows": rows,
                        "status": DataStatus.CACHED.value,
                    }
                )
                continue
            try:
                outcome = self.refresh_symbol(entry.symbol)
                prepared.append(
                    {
                        "symbol": entry.symbol,
                        "action": "refreshed",
                        "rows_stored": outcome.get("rows_stored", 0),
                        "status": outcome.get("status", DataStatus.UNAVAILABLE.value),
                    }
                )
            except ProviderError as exc:
                logger.error(
                    "Automatic data preparation failed for %s: %s", entry.symbol, exc.message
                )
                prepared.append(
                    {
                        "symbol": entry.symbol,
                        "action": "refresh_failed",
                        "status": DataStatus.ERROR.value,
                        "error": exc.message,
                    }
                )
        return prepared

    def get_price_series(
        self,
        symbol: str,
        start: date | None = None,
        end: date | None = None,
        instrument_key: str | None = None,
    ) -> dict:
        """Stored price series with explicit data status.

        Carries the stored live-quote freshness (Upstox timestamp + source) so
        the UI never shows a stale cached date when newer quote data exists.
        """
        entry = self._resolve_entry(symbol, instrument_key)
        prices: list[MarketPrice] = self.market_repo.get_prices(entry.symbol, start, end)
        if not prices:
            status = DataStatus.UNAVAILABLE.value
        elif self.market_repo.latest_trade_date(entry.symbol) and (
            date.today() - self.market_repo.latest_trade_date(entry.symbol)
        ).days <= 7:
            status = DataStatus.LIVE.value
        else:
            status = DataStatus.CACHED.value
        stored_quote = self.market_repo.get_stored_quote(entry.symbol)
        return {
            "symbol": entry.symbol,
            "name": entry.name,
            "status": status,
            "count": len(prices),
            "instrument_key": (instrument_key or "").strip() or getattr(entry, "instrument_key", None),
            "source": self.provider.name,
            "latest_trade_date": (
                prices[-1].trade_date.isoformat() if prices else None
            ),
            # Freshness: newest valid market observation available.
            "quote_timestamp": (stored_quote or {}).get("timestamp"),
            "quote_source": (stored_quote or {}).get("source"),
            "quote_last_price": (stored_quote or {}).get("last_price"),
            "prices": [
                {
                    "date": p.trade_date.isoformat(),
                    "open": p.open,
                    "high": p.high,
                    "low": p.low,
                    "close": p.close,
                    "volume": p.volume,
                }
                for p in prices
            ],
        }
