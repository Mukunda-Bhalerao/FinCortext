"""Application configuration.

All configuration is loaded from environment variables (optionally via a
`.env` file at the repository root). Secrets such as API keys are never
hardcoded; missing configuration must degrade gracefully rather than crash
the application.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List
import os

# Repository root = two levels above this file's directory
# (backend/app/core/config.py -> repo root).
REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (no external dependency).

    Only sets variables that are not already present in the environment so
    real environment variables always win.
    """
    if not path.is_file():
        return
    try:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except OSError:
        # A malformed .env must never crash the application.
        pass


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


def _split_csv(raw: str | None, default: List[str]) -> List[str]:
    if raw is None or not raw.strip():
        return list(default)
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    """Immutable application settings."""

    # --- News provider -------------------------------------------------
    news_api_key: str = field(default_factory=lambda: os.getenv("NEWS_API_KEY", "").strip())

    # --- Storage -------------------------------------------------------
    db_path: Path = field(
        default_factory=lambda: _resolve_path(
            os.getenv("FINCORTEXT_DB_PATH", "data/processed/fincortext.duckdb")
        )
    )

    # --- Backend -------------------------------------------------------
    host: str = field(default_factory=lambda: os.getenv("FINCORTEXT_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: _env_int("FINCORTEXT_PORT", 8000))
    cors_origins: List[str] = field(
        default_factory=lambda: _split_csv(
            os.getenv("FINCORTEXT_CORS_ORIGINS"),
            ["http://localhost:5173", "http://127.0.0.1:5173"],
        )
    )
    log_level: str = field(
        default_factory=lambda: os.getenv("FINCORTEXT_LOG_LEVEL", "INFO").upper()
    )

    # --- Market data ---------------------------------------------------
    market_history_days: int = field(
        default_factory=lambda: _env_int("FINCORTEXT_MARKET_HISTORY_DAYS", 730)
    )
    # Primary live market provider: "yfinance" (default) or "upstox".
    # yfinance stays available as fallback/research provider.
    live_market_provider: str = field(
        default_factory=lambda: os.getenv("LIVE_MARKET_PROVIDER", "yfinance").strip().lower() or "yfinance"
    )

    # --- Upstox --------------------------------------------------------
    # Token is read from UPSTOX_ACCESS_TOKEN only; never logged or exposed.
    upstox_access_token: str = field(
        default_factory=lambda: os.getenv("UPSTOX_ACCESS_TOKEN", "").strip()
    )
    upstox_base_url: str = field(
        default_factory=lambda: os.getenv("UPSTOX_BASE_URL", "https://api.upstox.com").strip().rstrip("/")
        or "https://api.upstox.com"
    )
    upstox_timeout_seconds: int = field(
        default_factory=lambda: _env_int("UPSTOX_TIMEOUT_SECONDS", 10)
    )

    # --- Sentiment model -----------------------------------------------
    sentiment_model_id: str = field(
        default_factory=lambda: os.getenv("FINCORTEXT_SENTIMENT_MODEL", "ProsusAI/finbert")
    )
    sentiment_cache_dir: Path = field(
        default_factory=lambda: _resolve_path(
            os.getenv("FINCORTEXT_SENTIMENT_CACHE_DIR", "data/cache/sentiment-model")
        )
    )

    # --- Behaviour flags ------------------------------------------------
    # When True the API may serve bundled sample fixtures, but ONLY when the
    # caller explicitly requests sample data. Sample data is never silently
    # substituted for live data.
    allow_sample_data: bool = field(
        default_factory=lambda: _env_bool("FINCORTEXT_ALLOW_SAMPLE_DATA", True)
    )

    @property
    def has_news_api_key(self) -> bool:
        return bool(self.news_api_key)

    @property
    def has_upstox_token(self) -> bool:
        return bool(self.upstox_access_token)

    def summary(self) -> dict:
        """Safe summary for logging/health checks (never exposes secrets)."""
        return {
            "db_path": str(self.db_path),
            "news_api_configured": self.has_news_api_key,
            "cors_origins": self.cors_origins,
            "log_level": self.log_level,
            "market_history_days": self.market_history_days,
            "live_market_provider": self.live_market_provider,
            "upstox_configured": self.has_upstox_token,
            "sentiment_model_id": self.sentiment_model_id,
            "allow_sample_data": self.allow_sample_data,
        }


def _resolve_path(raw: str) -> Path:
    """Resolve a configured path against the repository root if relative."""
    path = Path(raw)
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path


def get_settings() -> Settings:
    """Build settings from the current environment.

    A `.env` file at the repository root is loaded first (if present).
    """
    _load_dotenv(REPO_ROOT / ".env")
    return Settings()


# Module-level singleton used across the app. Tests may construct their own
# Settings instances directly.
settings = get_settings()