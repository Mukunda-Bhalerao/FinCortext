"""Daily usage budget for the language model, recorded in DuckDB.

Cloud models routed through Ollama have usage limits that the app cannot query, so FinCortext
keeps its own count and stops calling once the configured daily number of calls is used.
Every feature that uses the model has a deterministic fallback.
"""

from datetime import UTC, datetime

from app.db import Database
from app.errors import RateLimited
from app.tools.market_hours import to_ist


class LLMBudget:
    def __init__(self, db: Database, daily_calls: int):
        self._db = db
        self.daily_calls = daily_calls

    @staticmethod
    def _today():
        return to_ist(datetime.now(UTC)).date()

    def used_today(self) -> dict[str, int]:
        row = self._db.fetchone(
            "SELECT coalesce(sum(calls), 0), coalesce(sum(prompt_tokens), 0), "
            "coalesce(sum(output_tokens), 0) FROM llm_usage WHERE day = ?",
            [self._today()],
        )
        calls, prompt, output = row if row else (0, 0, 0)
        return {"calls": int(calls), "prompt_tokens": int(prompt), "output_tokens": int(output)}

    def check(self) -> None:
        if self.used_today()["calls"] >= self.daily_calls:
            raise RateLimited(
                f"Today's language-model budget of {self.daily_calls} calls is used up; "
                "FinCortext is using its built-in summaries until tomorrow (IST)."
            )

    def record(self, purpose: str, prompt_tokens: int, output_tokens: int) -> None:
        day = self._today()
        row = self._db.fetchone(
            "SELECT calls, prompt_tokens, output_tokens FROM llm_usage "
            "WHERE day = ? AND purpose = ?",
            [day, purpose],
        )
        calls, p, o = row if row else (0, 0, 0)
        self._db.execute(
            "INSERT OR REPLACE INTO llm_usage VALUES (?, ?, ?, ?, ?)",
            [day, purpose, calls + 1, p + prompt_tokens, o + output_tokens],
        )
