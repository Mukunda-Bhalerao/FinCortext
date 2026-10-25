"""Upstox token lifecycle. Tokens live only in the backend (DuckDB or .env)."""

import base64
import json
import logging
import secrets
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from app.config import Settings
from app.db import Database, _as_utc
from app.errors import AppError, ProviderRequestError
from app.providers.upstox import UpstoxProvider, authorization_url
from app.schemas.market import AuthStatus
from app.tools.market_hours import IST

log = logging.getLogger(__name__)

PROVIDER = "upstox"
_STATE_TTL_SECONDS = 600


def expected_expiry(obtained_at: datetime) -> datetime:
    """Upstox access tokens are documented to expire at 03:30 IST on the following day."""
    local = obtained_at.astimezone(IST)
    cutoff = local.replace(hour=3, minute=30, second=0, microsecond=0)
    if local >= cutoff:
        cutoff += timedelta(days=1)
    return cutoff.astimezone(UTC)


def token_expiry(token: str) -> datetime | None:
    """``exp`` claim of a JWT access token, read without verification and used only to warn
    before expiry. Upstox Analytics tokens carry a one-year ``exp``."""
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        claims = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
        return datetime.fromtimestamp(int(claims["exp"]), tz=UTC)
    except (ValueError, KeyError, TypeError):
        return None


class AuthService:
    def __init__(self, db: Database, settings: Settings):
        self._db = db
        self._settings = settings
        self._token: str | None = None
        self._source: str = "none"
        self._user_name: str | None = None
        self._obtained_at: datetime | None = None
        self._expires_at: datetime | None = None
        self._rejected = False
        self._problem: str | None = None
        self._states: dict[str, float] = {}
        self._listeners: list[Callable[[], None]] = []
        self._load()

    def _load(self) -> None:
        row = self._db.fetchone(
            "SELECT access_token, user_name, obtained_at FROM auth_tokens WHERE provider = ?",
            [PROVIDER],
        )
        if row:
            obtained = _as_utc(row[2])
            if expected_expiry(obtained) > datetime.now(UTC):
                self._token, self._user_name, self._obtained_at = row[0], row[1], obtained
                self._source, self._expires_at = "oauth", expected_expiry(obtained)
                return
            self._problem = "The saved Upstox session has expired. Reconnect Upstox."
        self._use_env_token()

    def _use_env_token(self) -> None:
        env_token = self._settings.upstox_access_token.get_secret_value().strip()
        if env_token:
            self._token, self._source = env_token, "env"
            self._expires_at = token_expiry(env_token)

    # --- observers ---------------------------------------------------------------

    def on_change(self, listener: Callable[[], None]) -> None:
        self._listeners.append(listener)

    def _notify(self) -> None:
        for listener in self._listeners:
            listener()

    # --- token access --------------------------------------------------------------

    def current_token(self) -> str | None:
        if self._token is None or self._rejected:
            return None
        if self._expires_at and self._expires_at <= datetime.now(UTC):
            self.mark_rejected("expired")
            return None
        return self._token

    def mark_rejected(self, reason: str) -> None:
        if self._rejected:
            return
        log.warning("Upstox token rejected (%s)", reason)
        self._rejected = True
        self._problem = (
            "UPSTOX_ACCESS_TOKEN in .env was rejected or has expired. Generate a new token."
            if self._source == "env"
            else "Upstox session expired or was revoked. Reconnect Upstox."
        )
        self._notify()

    # --- OAuth ---------------------------------------------------------------------

    def login_url(self) -> str:
        if not self._settings.upstox_oauth_configured:
            raise AppError(
                "Set UPSTOX_API_KEY and UPSTOX_API_SECRET in .env, then restart the backend.",
                code="oauth_not_configured",
                status_code=400,
            )
        now = time.monotonic()
        self._states = {s: t for s, t in self._states.items() if now - t < _STATE_TTL_SECONDS}
        state = secrets.token_urlsafe(24)
        self._states[state] = now
        return authorization_url(
            self._settings.upstox_api_key, self._settings.upstox_redirect_uri, state
        )

    async def complete_oauth(self, code: str, state: str) -> None:
        issued = self._states.pop(state, None)
        if issued is None or time.monotonic() - issued > _STATE_TTL_SECONDS:
            raise ProviderRequestError("Sign-in link expired or was not started here. Try again.")
        body = await UpstoxProvider.exchange_code(
            code,
            self._settings.upstox_api_key,
            self._settings.upstox_api_secret.get_secret_value(),
            self._settings.upstox_redirect_uri,
        )
        now = datetime.now(UTC)
        self._db.execute(
            "INSERT OR REPLACE INTO auth_tokens VALUES (?, ?, ?, ?, ?, ?)",
            [
                PROVIDER,
                body["access_token"],
                body.get("user_id"),
                body.get("user_name"),
                now,
                expected_expiry(now),
            ],
        )
        self._token, self._source = body["access_token"], "oauth"
        self._user_name, self._obtained_at = body.get("user_name"), now
        self._expires_at = expected_expiry(now)
        self._rejected, self._problem = False, None
        self._notify()

    def disconnect(self) -> None:
        self._db.execute("DELETE FROM auth_tokens WHERE provider = ?", [PROVIDER])
        self._token, self._source, self._user_name, self._obtained_at = None, "none", None, None
        self._expires_at = None
        self._rejected, self._problem = False, None
        self._use_env_token()
        self._notify()

    async def verify(self, provider: UpstoxProvider) -> None:
        """Validate the token with a market-data call (a 401 there marks it rejected), then
        fetch the account name if this token type is allowed to read it."""
        if self.current_token() is None:
            return
        try:
            await provider.get_market_status("NSE")
        except AppError as exc:
            if not self._rejected:
                log.warning("token check failed: %s", exc.code)
            return
        try:
            profile = await provider.get_profile()
            self._user_name = profile.user_name or self._user_name
        except AppError:
            pass  # profile is optional (not available to read-only analytics tokens)

    def status(self) -> AuthStatus:
        connected = self.current_token() is not None
        problem = self._problem
        if not connected and problem is None:
            problem = (
                "Upstox is not connected."
                if self._settings.upstox_oauth_configured
                else "Upstox API credentials are not configured in .env."
            )
        return AuthStatus(
            oauth_configured=self._settings.upstox_oauth_configured,
            connected=connected,
            token_source=self._source if connected else "none",  # type: ignore[arg-type]
            user_name=self._user_name if connected else None,
            expected_expiry=self._expires_at if connected else None,
            problem=None if connected else problem,
        )
