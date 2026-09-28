"""Google News RSS adapter implementing the NewsProvider contract.

Free, keyless retrieval for Indian equity news via public RSS search feeds
(no article-page scraping — only feed XML is fetched and parsed):

- Primary: Google News RSS search
  (https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en)
  with company-name query variants (short name -> full legal name ->
  symbol + " NSE"), stopping at the first variant returning >= 5 items.
- Secondary fallback inside the same provider: Yahoo Finance headlines RSS
  (https://feeds.finance.yahoo.com/rss/2.0/headline?s={SYMBOL}.NS&...).

Normalization mirrors the NewsAPI adapter at the boundary: canonical
NewsArticle with stable article_id (SHA-256 of link), content_hash audit
hash, source metadata, publication timestamp. Google appends " - Source" to
titles; the suffix is stripped into the source field. Never fabricates.

Politeness/robustness: browser-like User-Agent, 10s timeout, max 1
request/second, 2 retries with backoff, 6-hour per-query result cache.
Any failure raises ProviderError -> the existing graceful UNAVAILABLE path.
"""

from __future__ import annotations

import hashlib
import re
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from urllib.parse import quote_plus

import requests

from app.core.exceptions import ProviderError
from app.core.logging import get_logger
from app.domain.contracts.providers import NewsProvider
from app.domain.models.base import DataSourceType
from app.domain.models.news import NewsArticle

logger = get_logger("providers.googlenews_rss")

GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search"
YAHOO_RSS_URL = "https://feeds.finance.yahoo.com/rss/2.0/headline"
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT_SECONDS = 10
MIN_REQUEST_INTERVAL_SECONDS = 1.0
MAX_RETRIES = 2
RETRY_BACKOFF_SECONDS = (0.5, 1.5)
CACHE_TTL_SECONDS = 6 * 3600
MIN_ITEMS_PER_VARIANT = 5

_TAG_RE = re.compile(r"<[^>]+>")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _strip_html(raw: str | None) -> str | None:
    """Snippet text from RSS <description> HTML; None when empty."""
    if not raw:
        return None
    text = unescape(_TAG_RE.sub(" ", raw))
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _inner_text(element: ET.Element | None) -> str | None:
    """Full text of an element including nested markup children.

    Feed descriptions embed links/tables (``findtext`` would return only the
    text before the first child); serializing as text recovers everything.
    """
    if element is None:
        return None
    try:
        return ET.tostring(element, encoding="unicode", method="text") or None
    except Exception:
        return element.text


def parse_published_at(raw: str | None) -> datetime | None:
    """Parse RSS pubDate (RFC-2822). None on failure — never raises."""
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw.strip())
        if dt is not None and dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError, IndexError):
        return None


def split_title_source(title: str) -> tuple[str, str | None]:
    """Split Google's "Headline - Source Name" suffix into (title, source).

    Only the LAST " - " separator is treated as the source split, and only
    when both sides are non-empty — headlines containing hyphens are left
    intact otherwise.
    """
    text = (title or "").strip()
    if " - " not in text:
        return text, None
    head, _, tail = text.rpartition(" - ")
    head, tail = head.strip(), tail.strip()
    if not head or not tail:
        return text, None
    return head, tail


def _quote(core: str) -> str:
    core = (core or "").strip()
    return f'"{core}"' if core and " " in core else core


def query_variants(short_name: str | None, full_name: str | None, symbol: str | None) -> list[str]:
    """Ordered Google News queries: short name -> full name -> symbol + NSE.

    Each variant appends a market-recall tail. De-duplicated, order kept.
    """
    variants: list[str] = []
    seen: set[str] = set()

    def add(core: str | None) -> None:
        core = (core or "").strip()
        if not core or core.upper() in seen:
            return
        seen.add(core.upper())
        variants.append(f"{core} stock OR shares OR results when:30d")

    add(_quote(short_name))
    add(_quote(full_name))
    if symbol and (symbol or "").strip():
        add(f"{symbol.strip().upper()} NSE")
    return variants


def rss_query_variants(entry) -> list[str]:
    """Pipe-form variant cores for a universe entry: SHORT|FULL|SYMBOL.

    Used by NewsService so the RSS provider searches short name first, then
    the full legal name, then the bare symbol — stopping at the first variant
    with enough items.
    """
    from app.data.universe.company_names import short_company_name

    name = (getattr(entry, "name", None) or "").strip()
    symbol = (getattr(entry, "symbol", None) or "").strip().upper()
    short = short_company_name(name)
    cores: list[tuple[str | None, str | None, str | None]] = []
    seen: set[str] = set()
    out: list[str] = []
    for triple in ((short, name, symbol), (name, name, symbol), (short, short, symbol)):
        key = "|".join(((c or "").upper() for c in triple))
        if key in seen:
            continue
        seen.add(key)
        cores.append(triple)
    for s, f, sym in cores:
        out.append("|".join([(s or ""), (f or ""), (sym or "")]))
    # Fall back to a bare-symbol core when names are missing entirely.
    if not out and symbol:
        out.append(f"||{symbol}")
    return out


class GoogleNewsRssProvider(NewsProvider):
    """Google News RSS (+ Yahoo headlines fallback). Keyless by design."""

    name = "google_news_rss"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_request_at = 0.0
        # query -> (fetched_at_epoch, articles). 6h TTL: preparation must not
        # refetch fresh results; stored news is reused instead.
        self._cache: dict[str, tuple[float, list[NewsArticle]]] = {}

    @property
    def is_configured(self) -> bool:
        # No key, no account, no quota — always available (network permitting).
        return True

    # -- NewsProvider contract -------------------------------------------------

    def fetch_articles(
        self,
        query: str,
        from_date: str | None = None,
        to_date: str | None = None,
        page_size: int = 50,
    ) -> list[NewsArticle]:
        """Fetch via Google News RSS variants, then Yahoo fallback.

        `query` may be a plain company string ("Adani Power") or a pre-built
        variant; short/full/symbol forms are derived when the query looks
        like "NAME|SYMBOL". Date bounds are accepted for contract symmetry
        but RSS feeds are inherently recency-ordered (no server-side filter).
        """
        short, full, symbol = self._split_query(query)
        cached = self._cache_get(query)
        if cached is not None:
            return list(cached)
        collected: list[NewsArticle] = []
        seen_ids: set[str] = set()
        errors: list[str] = []
        for variant in query_variants(short, full, symbol):
            try:
                items = self._fetch_google_variant(variant)
            except ProviderError as exc:
                errors.append(exc.message)
                continue
            for article in items:
                if article.article_id not in seen_ids:
                    seen_ids.add(article.article_id)
                    collected.append(article)
            if len(items) >= MIN_ITEMS_PER_VARIANT:
                break
        if len(collected) < MIN_ITEMS_PER_VARIANT and symbol:
            try:
                for article in self._fetch_yahoo(symbol):
                    if article.article_id not in seen_ids:
                        seen_ids.add(article.article_id)
                        collected.append(article)
            except ProviderError as exc:
                errors.append(exc.message)
        if not collected and errors:
            raise ProviderError(
                f"Google News RSS retrieval failed: {errors[0]}",
                details={"provider": self.name, "query": query},
            )
        limited = collected[: max(1, min(int(page_size or 50), 100))]
        self._cache_put(query, limited)
        return limited

    # -- query handling ----------------------------------------------------------

    @staticmethod
    def _split_query(query: str) -> tuple[str | None, str | None, str | None]:
        """Accept "SHORT|FULL|SYMBOL" or a plain string (used as short name).

        NewsService passes NewsAPI-style OR-queries; those are passed through
        as a single variant core so RSS still searches something sensible.
        """
        raw = (query or "").strip()
        if "|" in raw:
            parts = [p.strip().strip('"') for p in raw.split("|")]
            short = parts[0] or None
            full = parts[1] if len(parts) > 1 else None
            symbol = parts[2] if len(parts) > 2 else None
            return short, full, symbol
        # Strip a trailing variant tail if the caller already appended one.
        lowered = raw.lower()
        for tail in (" stock or shares or results when:30d",):
            if lowered.endswith(tail):
                raw = raw[: -len(tail)].strip().strip('"')
                break
        return raw or None, None, None

    # -- HTTP ----------------------------------------------------------------------

    def _throttled_get(self, url: str, params: dict) -> requests.Response:
        """Single GET with politeness delay + retries. Raises ProviderError."""
        with self._lock:
            wait = MIN_REQUEST_INTERVAL_SECONDS - (time.monotonic() - self._last_request_at)
            if wait > 0:
                time.sleep(wait)
            last_error: Exception | None = None
            for attempt in range(MAX_RETRIES + 1):
                try:
                    resp = requests.get(
                        url,
                        params=params,
                        headers={"User-Agent": BROWSER_USER_AGENT, "Accept": "application/rss+xml"},
                        timeout=REQUEST_TIMEOUT_SECONDS,
                    )
                    self._last_request_at = time.monotonic()
                    if resp.status_code == 429:
                        last_error = RuntimeError("HTTP 429 rate limited")
                    elif resp.status_code != 200:
                        last_error = RuntimeError(f"HTTP {resp.status_code}")
                    else:
                        return resp
                except requests.RequestException as exc:
                    last_error = exc
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_BACKOFF_SECONDS[min(attempt, len(RETRY_BACKOFF_SECONDS) - 1)])
            raise ProviderError(
                f"RSS request failed after {MAX_RETRIES + 1} attempts: {last_error}",
                details={"provider": self.name, "url": url},
            )

    # -- feed fetching ---------------------------------------------------------------

    def _fetch_google_variant(self, variant_query: str) -> list[NewsArticle]:
        """One Google News RSS search; returns normalized articles."""
        params = {"q": variant_query, "hl": "en-IN", "gl": "IN", "ceid": "IN:en"}
        # quote_plus applied by requests params encoding; kept explicit here
        # only for logging-free URL construction parity in tests.
        _ = quote_plus(variant_query)
        resp = self._throttled_get(GOOGLE_NEWS_RSS_URL, params)
        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError as exc:
            raise ProviderError(
                f"Google News RSS returned malformed XML: {exc}",
                details={"provider": self.name},
            ) from exc
        articles: list[NewsArticle] = []
        for item in root.iter("item"):
            article = self._normalize_google_item(item)
            if article is not None:
                articles.append(article)
        logger.info("Google News RSS variant %r -> %d items", variant_query[:40], len(articles))
        return articles

    def _fetch_yahoo(self, symbol: str) -> list[NewsArticle]:
        """Yahoo Finance headlines RSS fallback for one NSE symbol."""
        ticker = f"{symbol.strip().upper()}.NS"
        resp = self._throttled_get(
            YAHOO_RSS_URL, {"s": ticker, "region": "IN", "lang": "en-IN"}
        )
        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError as exc:
            raise ProviderError(
                f"Yahoo RSS returned malformed XML: {exc}",
                details={"provider": self.name},
            ) from exc
        articles: list[NewsArticle] = []
        for item in root.iter("item"):
            title = ((item.findtext("title") or "").strip())
            if not title:
                continue
            link = (item.findtext("link") or "").strip() or None
            description = _strip_html(_inner_text(item.find("description")))
            published_at = parse_published_at(item.findtext("pubDate"))
            article_id = _sha256(link) if link else _sha256(
                f"{title}|{item.findtext('pubDate') or ''}"
            )
            articles.append(
                NewsArticle(
                    article_id=article_id,
                    title=title,
                    description=description,
                    content=None,
                    source="Yahoo Finance",
                    source_url=link,
                    published_at=published_at,
                    language="en",
                    entity_id=None,  # associated by the service layer
                    content_hash=_sha256(f"{title}|{description or ''}|"),
                    source_type=DataSourceType.GOOGLE_NEWS_RSS,
                    source_name=self.name,
                )
            )
        logger.info("Yahoo RSS fallback %s -> %d items", ticker, len(articles))
        return articles

    # -- normalization -----------------------------------------------------------------

    def _normalize_google_item(self, item: ET.Element) -> NewsArticle | None:
        """Convert one Google News <item> to the canonical model (None skips)."""
        raw_title = (item.findtext("title") or "").strip()
        if not raw_title:
            return None
        title, suffix_source = split_title_source(raw_title)
        link = (item.findtext("link") or "").strip() or None
        # Prefer the explicit <source> element; fall back to the title suffix.
        source_el = item.find("source")
        source = ((source_el.text or "").strip() if source_el is not None else "") or suffix_source
        description = _strip_html(_inner_text(item.find("description")))
        published_at = parse_published_at(item.findtext("pubDate"))
        article_id = _sha256(link) if link else _sha256(
            f"{title}|{item.findtext('pubDate') or ''}"
        )
        return NewsArticle(
            article_id=article_id,
            title=title,
            description=description,
            content=None,
            source=source,
            source_url=link,
            published_at=published_at,
            language="en",
            entity_id=None,  # associated by the service layer, not the provider
            content_hash=_sha256(f"{title}|{description or ''}|"),
            source_type=DataSourceType.GOOGLE_NEWS_RSS,
            source_name=self.name,
        )

    # -- cache ---------------------------------------------------------------------------

    def _cache_get(self, query: str) -> list[NewsArticle] | None:
        with self._lock:
            hit = self._cache.get((query or "").strip())
            if hit is None:
                return None
            fetched_at, articles = hit
            if time.monotonic() - fetched_at > CACHE_TTL_SECONDS:
                del self._cache[(query or "").strip()]
                return None
            logger.info("Google News RSS cache hit for %r", (query or "")[:40])
            return list(articles)

    def _cache_put(self, query: str, articles: list[NewsArticle]) -> None:
        with self._lock:
            self._cache[(query or "").strip()] = (time.monotonic(), list(articles))
