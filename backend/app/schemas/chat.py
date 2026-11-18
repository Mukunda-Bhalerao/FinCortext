from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.insights import Fact, Turn

Tone = Literal["up", "down", "muted"]


class ChatContext(BaseModel):
    """Where the user is in the app, so "it" and "my account" mean something."""

    path: str | None = Field(None, max_length=200)
    symbol: str | None = Field(None, max_length=40)
    portfolio_id: str | None = Field(None, max_length=40)


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    history: list[Turn] = Field(default_factory=list, max_length=8)
    context: ChatContext = Field(default_factory=ChatContext)


class Stat(BaseModel):
    label: str
    value: str
    tone: Tone | None = None
    hint: str | None = None


class Row(BaseModel):
    label: str
    sub: str | None = None
    value: str | None = None
    change: float | None = None  # a fraction; coloured by sign
    to: str | None = None  # a page in the app
    href: str | None = None  # an external link (news)


class Bar(BaseModel):
    label: str
    value: float  # a fraction
    note: str | None = None


class ChatCard(BaseModel):
    kind: Literal["stats", "rows", "bars", "definition", "steps", "spark"]
    title: str
    note: str | None = None
    stats: list[Stat] = []
    rows: list[Row] = []
    bars: list[Bar] = []
    steps: list[str] = []
    text: str | None = None
    points: list[float] = []


class ChatAction(BaseModel):
    label: str
    to: str


class ChatAnswer(BaseModel):
    answer: str
    tool: str
    rule: str  # the routing rule that fired
    cards: list[ChatCard] = []
    facts: list[Fact] = []  # what the answer rests on
    follow_ups: list[str] = []
    actions: list[ChatAction] = []
    answered_by: Literal["engine", "model"] = "engine"
    model: str | None = None
    notice: str | None = None
    symbol: str | None = None  # the stock in focus, carried to the next question
    generated_at: datetime


class Nudge(BaseModel):
    """One thing worth the user's attention, with the evidence and a next step."""

    id: str
    kind: Literal["account", "watchlist", "ipo", "strategy", "market", "research", "start"]
    severity: Literal["high", "medium", "low"]
    title: str
    body: str
    symbol: str | None = None
    action_label: str | None = None
    action_to: str | None = None
    ask: str | None = None  # a question the assistant can answer about it


class ProgressStep(BaseModel):
    key: str
    label: str
    done: bool
    to: str


class TodayFeed(BaseModel):
    nudges: list[Nudge]
    progress: list[ProgressStep]
    gaps: list[str] = []
    generated_at: datetime
