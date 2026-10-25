import asyncio
import base64
import json
from datetime import UTC, datetime

import httpx
import pytest

from app.errors import ProviderRequestError, TokenInvalid
from app.providers.upstox import API_BASE, UpstoxProvider
from app.services.auth import token_expiry

UNAUTHORIZED = {"status": "error", "errors": [{"errorCode": "UDAPI1221", "message": "x"}]}


def _provider(handler) -> tuple[UpstoxProvider, list[str]]:
    rejected: list[str] = []
    p = UpstoxProvider(lambda: "tok", rejected.append)
    p._client = httpx.AsyncClient(base_url=API_BASE, transport=httpx.MockTransport(handler))
    return p, rejected


def test_profile_401_does_not_reject_read_only_token():
    p, rejected = _provider(lambda req: httpx.Response(401, json=UNAUTHORIZED))
    with pytest.raises(ProviderRequestError):
        asyncio.run(p.get_profile())
    assert rejected == []


def test_market_data_401_rejects_token():
    p, rejected = _provider(lambda req: httpx.Response(401, json=UNAUTHORIZED))
    with pytest.raises(TokenInvalid):
        asyncio.run(p.get_market_status("NSE"))
    assert rejected == ["UDAPI1221"]


def test_rate_limit_is_retried_then_succeeds():
    calls = []

    def handler(req):
        calls.append(req)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"data": {"status": "NORMAL_OPEN"}})

    p, _ = _provider(handler)
    assert asyncio.run(p.get_market_status("NSE")) == "NORMAL_OPEN"
    assert len(calls) == 2


def _jwt(claims: dict) -> str:
    enc = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"hdr.{enc}.sig"


def test_token_expiry_reads_exp_claim():
    assert token_expiry(_jwt({"exp": 1822428000})) == datetime.fromtimestamp(1822428000, UTC)
    assert token_expiry("not-a-jwt") is None
    assert token_expiry(_jwt({"sub": "x"})) is None
