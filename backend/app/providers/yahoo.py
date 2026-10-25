"""Company fundamentals and analyst consensus from Yahoo Finance's public quote-summary API.

Unofficial and unversioned: every field is optional, and callers must treat a missing value
as a data gap. Symbols are the NSE trading symbol with the ``.NS`` suffix.
"""

import asyncio
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from urllib.parse import quote

import httpx

from app.errors import NotFound, ProviderUnavailable

log = logging.getLogger(__name__)

SOURCE = "Yahoo Finance quote summary"
_BASE = "https://query2.finance.yahoo.com/v10/finance/quoteSummary/"
_MODULES = ",".join(
    (
        "financialData",
        "defaultKeyStatistics",
        "summaryDetail",
        "assetProfile",
        "recommendationTrend",
        "esgScores",
    )
)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
    ),
    "Accept": "*/*",  # the session-token endpoint answers 406 to application/json
}


@dataclass
class Fundamentals:
    symbol: str
    fetched_at: datetime
    sector: str | None = None
    industry: str | None = None
    currency: str | None = None
    price: float | None = None
    market_cap: float | None = None
    trailing_pe: float | None = None
    forward_pe: float | None = None
    price_to_book: float | None = None
    trailing_eps: float | None = None
    roe: float | None = None
    roe_derived: bool = False
    profit_margin: float | None = None
    operating_margin: float | None = None
    revenue_growth: float | None = None
    earnings_growth: float | None = None
    debt_to_equity: float | None = None  # ratio (Yahoo reports a percentage)
    dividend_yield: float | None = None
    recommendation_mean: float | None = None  # 1 strong buy .. 5 strong sell
    analyst_count: int | None = None
    target_mean: float | None = None
    rating_counts: dict[str, int] = field(default_factory=dict)
    esg_total: float | None = None
    most_recent_quarter: datetime | None = None

    def to_json(self) -> dict:
        d = asdict(self)
        for k in ("fetched_at", "most_recent_quarter"):
            d[k] = d[k].isoformat() if d[k] else None
        return d

    @classmethod
    def from_json(cls, d: dict) -> "Fundamentals":
        d = dict(d)
        for k in ("fetched_at", "most_recent_quarter"):
            d[k] = datetime.fromisoformat(d[k]) if d.get(k) else None
        return cls(**d)


def _raw(module: dict | None, key: str) -> float | None:
    if not module:
        return None
    v = module.get(key)
    if isinstance(v, dict):
        v = v.get("raw")
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None


def parse_summary(symbol: str, result: dict, fetched_at: datetime) -> Fundamentals:
    fin = result.get("financialData") or {}
    stats = result.get("defaultKeyStatistics") or {}
    summ = result.get("summaryDetail") or {}
    prof = result.get("assetProfile") or {}
    esg = result.get("esgScores") or {}
    f = Fundamentals(symbol=symbol, fetched_at=fetched_at)
    f.sector = prof.get("sector") or None
    f.industry = prof.get("industry") or None
    f.currency = fin.get("financialCurrency") or summ.get("currency")
    f.price = _raw(fin, "currentPrice")
    f.market_cap = _raw(summ, "marketCap")
    f.trailing_pe = _raw(summ, "trailingPE")
    f.forward_pe = _raw(summ, "forwardPE") or _raw(stats, "forwardPE")
    f.price_to_book = _raw(stats, "priceToBook")
    f.trailing_eps = _raw(stats, "trailingEps")
    f.roe = _raw(fin, "returnOnEquity")
    if f.roe is None:
        income, book, shares = (
            _raw(stats, "netIncomeToCommon"),
            _raw(stats, "bookValue"),
            _raw(stats, "sharesOutstanding"),
        )
        if income is not None and book and shares:
            f.roe, f.roe_derived = income / (book * shares), True
    f.profit_margin = _raw(fin, "profitMargins")
    f.operating_margin = _raw(fin, "operatingMargins")
    f.revenue_growth = _raw(fin, "revenueGrowth")
    f.earnings_growth = _raw(fin, "earningsGrowth")
    de = _raw(fin, "debtToEquity")
    f.debt_to_equity = de / 100.0 if de is not None else None
    f.dividend_yield = _raw(summ, "dividendYield")
    f.recommendation_mean = _raw(fin, "recommendationMean")
    count = _raw(fin, "numberOfAnalystOpinions")
    f.analyst_count = int(count) if count is not None else None
    f.target_mean = _raw(fin, "targetMeanPrice")
    trend = (result.get("recommendationTrend") or {}).get("trend") or []
    current = next((t for t in trend if t.get("period") == "0m"), None)
    if current:
        f.rating_counts = {
            k: int(current[k])
            for k in ("strongBuy", "buy", "hold", "sell", "strongSell")
            if isinstance(current.get(k), int)
        }
    f.esg_total = _raw(esg, "totalEsg")
    mrq = _raw(stats, "mostRecentQuarter")
    f.most_recent_quarter = datetime.fromtimestamp(mrq, UTC) if mrq else None
    return f


class YahooProvider:
    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._crumb: str | None = None
        self._lock = asyncio.Lock()
        self._slots = asyncio.Semaphore(3)

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=15.0, headers=_HEADERS, follow_redirects=True)
        return self._client

    async def _ensure_crumb(self, renew: bool = False) -> str:
        async with self._lock:
            if self._crumb and not renew:
                return self._crumb
            client = self._http()
            try:
                await client.get("https://fc.yahoo.com")  # sets the session cookie; status varies
                resp = await client.get("https://query1.finance.yahoo.com/v1/test/getcrumb")
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                raise ProviderUnavailable("Could not open a Yahoo Finance session.") from exc
            crumb = resp.text.strip()
            if not crumb or "<" in crumb:
                raise ProviderUnavailable("Yahoo Finance did not issue a session token.")
            self._crumb = crumb
            return crumb

    async def fundamentals(self, nse_symbol: str) -> Fundamentals:
        symbol = f"{nse_symbol}.NS"
        async with self._slots:
            for attempt in range(2):
                crumb = await self._ensure_crumb(renew=attempt > 0)
                try:
                    resp = await self._http().get(
                        _BASE + quote(symbol, safe=""),
                        params={"modules": _MODULES, "crumb": crumb},
                    )
                except httpx.HTTPError as exc:
                    raise ProviderUnavailable("Yahoo Finance is not reachable.") from exc
                if resp.status_code == 401 and attempt == 0:
                    continue
                break
        if resp.status_code == 404:
            raise NotFound(f"Yahoo Finance has no record for {symbol}.")
        if resp.status_code != 200:
            raise ProviderUnavailable(f"Yahoo Finance returned HTTP {resp.status_code}.")
        results = ((resp.json() or {}).get("quoteSummary") or {}).get("result") or []
        if not results:
            raise NotFound(f"Yahoo Finance has no record for {symbol}.")
        return parse_summary(symbol, results[0], datetime.now(UTC))

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
