from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.tracker import Headline

Stage = Literal["upcoming", "open", "closed", "listed"]
Board = Literal["mainboard", "sme"]


class Subscription(BaseModel):
    qib: float | None = None
    nii: float | None = None
    nii_big: float | None = None
    nii_small: float | None = None
    retail: float | None = None
    employee: float | None = None
    shareholder: float | None = None
    total: float | None = None


class ListingOdds(BaseModel):
    """How past NSE issues with similar demand opened on listing day."""

    measure: Literal["qib", "total"]
    bucket: str
    sample: int
    above_issue: float
    average_gain: float
    median_gain: float
    worst: float
    best: float
    text: str


class Listing(BaseModel):
    instrument_key: str | None
    listing_open: float | None
    listing_close: float | None
    listing_gain: float | None  # open on listing day vs issue price
    price: float | None
    price_basis: str | None
    since_issue: float | None  # price now vs issue price


class IpoIssue(BaseModel):
    symbol: str
    company: str
    board: Board
    stage: Stage
    open_date: date | None
    close_date: date | None
    listing_date: date | None
    price_low: float | None
    price_high: float | None
    issue_price: float | None
    lot_size: int | None
    min_investment: float | None  # one lot at the top of the band
    industry: str | None = None
    subscription: Subscription | None = None
    subscription_note: str | None = None  # e.g. "bidding still open: day 2 of 3"
    odds: ListingOdds | None = None
    listing: Listing | None = None
    signals: list[str] = []  # plain facts that matter for the decision, good and bad


class MoodStat(BaseModel):
    days: int
    listed: int
    above_issue_at_open: float | None
    median_listing_gain: float | None
    above_issue_now: float | None


class IpoOverview(BaseModel):
    open: list[IpoIssue]
    upcoming: list[IpoIssue]
    awaiting_listing: list[IpoIssue]
    recent_listings: list[IpoIssue]
    strongest: list[str]  # symbols of open/closed issues ranked by demand and track record
    mood: list[MoodStat]
    odds_table: list[ListingOdds]
    history_size: int
    history_complete: bool
    news: list[Headline]
    as_of: datetime
    gaps: list[str]


class IpoDetail(BaseModel):
    issue: IpoIssue
    facts: dict[str, str]  # NSE issue information, title -> text
    lead_managers: list[str]
    documents: dict[str, str]  # label -> NSE archive link
    price_series: list[dict]  # [{time, value}] daily closes since listing
    news: list[Headline]
    as_of: datetime
    gaps: list[str]
