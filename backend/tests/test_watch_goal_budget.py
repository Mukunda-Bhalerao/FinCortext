import pytest

from app.db import Database
from app.errors import RateLimited
from app.schemas.insights import Fact
from app.services.llm_budget import LLMBudget
from app.services.watcher import Watcher
from app.tools import backtest as B


def test_monthly_returns_compound_blocks():
    m = B.monthly_returns([0.01] * 42)
    assert len(m) == 2 and abs(m[0] - (1.01**21 - 1)) < 1e-12


def test_goal_paths_are_reproducible_and_include_contributions():
    monthly = [0.01, -0.02, 0.015, 0.0, 0.02, -0.01] * 10
    a = B.goal_paths(monthly, 5, 100_000, 5_000, samples=200)
    assert a == B.goal_paths(monthly, 5, 100_000, 5_000, samples=200)
    assert len(a) == 200 and all(len(p) == 5 for p in a)
    flat = B.goal_paths([0.0] * 24, 2, 100_000, 1_000, samples=10)
    assert all(abs(p[-1] - 124_000) < 1e-6 for p in flat)  # no growth: only contributions


def test_budget_refuses_calls_past_the_daily_limit():
    db = Database(":memory:")
    budget = LLMBudget(db, 2)
    budget.check()
    budget.record("ask", 100, 20)
    budget.record("brief", 50, 10)
    assert budget.used_today() == {"calls": 2, "prompt_tokens": 150, "output_tokens": 30}
    with pytest.raises(RateLimited):
        budget.check()


def test_events_are_stored_once_and_can_be_marked_seen():
    db = Database(":memory:")
    w = Watcher(db, None, None, None, None, None, None, lambda: [])  # type: ignore[arg-type]
    fact = Fact(id="F1", text="x", source="s", basis="observed")
    assert w.add("move:INFY:2026-10-27", "market", "medium", "t", "b", [fact], "INFY")
    assert not w.add("move:INFY:2026-10-27", "market", "medium", "t", "b", [fact], "INFY")
    items, unread = w.recent()
    assert len(items) == 1 and unread == 1 and items[0]["facts"][0]["text"] == "x"
    w.mark_seen()
    assert w.recent()[1] == 0


def test_cooldown_and_daily_cap_keep_alerts_quiet():
    db = Database(":memory:")
    w = Watcher(db, None, None, None, None, None, None, lambda: [])  # type: ignore[arg-type]
    assert w.add("research:INFY:1", "research", "low", "t", "b", [], "INFY")
    assert not w.add("research:INFY:2", "research", "low", "t", "b", [], "INFY")  # cooldown
    assert w.add("research:INFY:3", "research", "medium", "t", "b", [], "INFY")  # more severe
    for i in range(10):
        w.add(f"move:S{i}", "market", "low", "t", "b", [], f"S{i}")
    items, _ = w.recent(100)
    assert len([e for e in items if e["severity"] != "high"]) == 6  # daily cap
    assert w.add("drawdown:x", "portfolio", "high", "t", "b", [])  # urgent alerts bypass the cap
