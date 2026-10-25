import pytest
from pydantic import SecretStr
from starlette.websockets import WebSocketDisconnect

TOKEN = "secret-token-value-123"


def test_health_and_search_without_credentials(make_client):
    client = make_client()
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["upstox"]["connected"] is False
    assert body["upstox"]["oauth_configured"] is False
    hits = client.get("/api/instruments/search", params={"q": "relia"}).json()
    assert hits[0]["instrument_key"] == "NSE_EQ|INE002A01018"


def test_market_data_without_token_is_explicit_503(make_client):
    client = make_client()
    resp = client.get("/api/candles", params={"key": "NSE_EQ|INE002A01018", "tf": "1D"})
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "provider_not_connected"


def test_unknown_instrument_never_reaches_provider(make_client):
    resp = make_client().get("/api/candles", params={"key": "NSE_EQ|INE999X99999", "tf": "1D"})
    assert resp.status_code == 404


def test_invalid_timeframe_rejected(make_client):
    resp = make_client().get("/api/candles", params={"key": "NSE_EQ|INE002A01018", "tf": "2D"})
    assert resp.status_code == 422


def test_token_is_never_exposed(make_client):
    client = make_client(upstox_access_token=SecretStr(TOKEN))
    for path in ("/api/health", "/api/auth/status"):
        text = client.get(path).text
        assert TOKEN not in text
    assert client.get("/api/auth/status").json()["token_source"] == "env"


def test_login_requires_configuration(make_client):
    resp = make_client().get("/api/auth/upstox/login", follow_redirects=False)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "oauth_not_configured"


def test_login_redirects_to_upstox_with_state(make_client):
    client = make_client(upstox_api_key="key123", upstox_api_secret=SecretStr("s"))
    resp = client.get("/api/auth/upstox/login", follow_redirects=False)
    assert resp.status_code == 302
    location = resp.headers["location"]
    assert location.startswith("https://api.upstox.com/v2/login/authorization/dialog?")
    assert "client_id=key123" in location and "state=" in location
    assert "secret" not in location


def test_callback_with_unknown_state_is_rejected(make_client):
    client = make_client(upstox_api_key="key123", upstox_api_secret=SecretStr("s"))
    resp = client.get(
        "/api/auth/upstox/callback",
        params={"code": "abc", "state": "forged"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "upstox=error" in resp.headers["location"]


def test_watchlist_roundtrip_validates_keys(make_client):
    client = make_client()
    assert client.put("/api/watchlist", params={"key": "NSE_EQ|INE002A01018"}).status_code == 204
    assert client.put("/api/watchlist", params={"key": "NSE_EQ|BOGUS0000"}).status_code == 404
    rows = client.app.state.services.market.watchlist_keys()
    assert rows == ["NSE_EQ|INE002A01018"]
    assert client.delete("/api/watchlist", params={"key": "NSE_EQ|INE002A01018"}).status_code == 204


def test_websocket_rejects_foreign_origin(make_client):
    client = make_client()
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            "/api/ws/live", headers={"origin": "https://evil.example"}
        ) as ws:
            ws.receive_json()


def test_websocket_sends_status_and_accepts_subscription(make_client):
    client = make_client()
    with client.websocket_connect(
        "/api/ws/live", headers={"origin": "http://localhost:5173"}
    ) as ws:
        first = ws.receive_json()
        assert first["type"] == "status"
        assert first["market"]["state"] in {"open", "pre_open", "closed"}
        ws.send_json({"action": "subscribe", "keys": ["NSE_EQ|INE002A01018", "NSE_EQ|BOGUS"]})


def test_stock_summary_degrades_without_provider(make_client):
    body = make_client().get("/api/stocks/RELIANCE").json()
    assert body["instrument"]["isin"] == "INE002A01018"
    assert body["quote"] is None and body["week52_high"] is None
    assert body["problems"]
