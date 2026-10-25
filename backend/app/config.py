from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    upstox_api_key: str = ""
    upstox_api_secret: SecretStr = SecretStr("")
    upstox_redirect_uri: str = "http://localhost:8000/api/auth/upstox/callback"
    # Optional manually generated token; an OAuth token stored by the app takes precedence.
    upstox_access_token: SecretStr = SecretStr("")

    duckdb_path: Path = Field(default=Path("./data/fincortext.duckdb"))
    frontend_url: str = "http://localhost:5173"

    # Live updates: "stream" uses the Upstox market data WebSocket and falls back to
    # quote polling if the stream cannot be established; "poll" uses polling only.
    live_mode: str = "stream"
    poll_interval_seconds: float = 3.0

    news_enabled: bool = True

    # Optional language layer: "none" (templated text only) or "ollama". It phrases agent
    # rationales, writes the portfolio brief and answers questions, always from computed facts.
    llm_provider: str = "none"
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = ""
    # Only for calling ollama.com directly; a signed-in local Ollama needs no key.
    ollama_api_key: SecretStr = SecretStr("")
    log_level: str = "INFO"

    @property
    def db_path(self) -> Path:
        path = self.duckdb_path
        return path if path.is_absolute() else (BACKEND_ROOT / path).resolve()

    @property
    def allowed_origins(self) -> list[str]:
        base = self.frontend_url.rstrip("/")
        return sorted({base, "http://localhost:5173", "http://127.0.0.1:5173"})

    @property
    def upstox_oauth_configured(self) -> bool:
        return bool(self.upstox_api_key and self.upstox_api_secret.get_secret_value())


@lru_cache
def get_settings() -> Settings:
    return Settings()
