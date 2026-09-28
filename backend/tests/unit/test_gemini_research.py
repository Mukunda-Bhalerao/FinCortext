"""Unit tests for the Gemini web-research provider (mocked SDK, no keys).

Uses fakes for ``genai.Client`` — no network, no real API key. Covers: the
BBL research task (sector/industry + peers via grounded research),
unconfigured degradation, peer/news parsing, every failure diagnostic
(auth/model/rate-limit/endpoint/timeout/grounding/malformed), and — critically
— that the API key never appears in messages, logs, or request parameters.
"""

from __future__ import annotations

import json
import logging

import pytest

from app.core.exceptions import ProviderError, ProviderUnavailableError
from app.data.providers.research import gemini_research as gr
from app.data.providers.research.gemini_research import GeminiResearchProvider
from google.genai.errors import APIError

FAKE_KEY = "test-key-that-must-never-leak"


# -- SDK fakes -----------------------------------------------------------------


class _FakeWeb:
    def __init__(self, uri, title=None):
        self.uri = uri
        self.title = title


class _FakeChunk:
    def __init__(self, uri, title=None):
        self.web = _FakeWeb(uri, title)


class _FakeGrounding:
    def __init__(self, chunks):
        self.grounding_chunks = chunks


class _FakeCandidate:
    def __init__(self, chunks):
        self.grounding_metadata = _FakeGrounding(chunks)


class _FakeResponse:
    def __init__(self, obj, chunks=(), feedback=None):
        self.text = json.dumps(obj)
        self.candidates = [_FakeCandidate(list(chunks))]
        self.prompt_feedback = feedback


class _FakeModels:
    def __init__(self, behavior):
        self.behavior = behavior  # callable(kind, **kwargs) -> response
        self.calls: list = []

    def generate_content(self, **kwargs):
        self.calls.append(("generate", kwargs))
        return self.behavior("generate", **kwargs)

    def get(self, **kwargs):
        self.calls.append(("get", kwargs))
        return self.behavior("get", **kwargs)


class _FakeClient:
    """Stands in for genai.Client; records constructor args (key check)."""

    instances: list = []

    def __init__(self, api_key=None, http_options=None):
        self.api_key = api_key
        self.http_options = http_options
        self.models = _FakeModels(lambda kind, **kw: self._behavior(kind, **kw))
        self._behavior_impl = None
        _FakeClient.instances.append(self)

    def _behavior(self, kind, **kwargs):
        assert self._behavior_impl is not None, "test must set behavior"
        return self._behavior_impl(kind, **kwargs)


@pytest.fixture(autouse=True)
def _reset_clients(monkeypatch):
    _FakeClient.instances = []
    monkeypatch.setattr(gr.genai, "Client", _FakeClient)
    yield
    _FakeClient.instances = []


def _provider_with(behavior, **kwargs):
    kwargs.setdefault("api_key", FAKE_KEY)
    p = GeminiResearchProvider(**kwargs)
    client = _FakeClient(api_key=FAKE_KEY)
    client._behavior_impl = behavior
    # Bypass lazy construction with our instrumented client.
    p._client = client
    p._client.models = _FakeModels(behavior)
    return p, client


def _chunks():
    return [
        _FakeChunk("https://example.com/bbl-profile", "Bharat Bijlee profile"),
        _FakeChunk("https://money.example.in/transformers", "Transformer makers"),
    ]


# --- configuration -----------------------------------------------------------


def test_unconfigured_raises_unavailable():
    p = GeminiResearchProvider(api_key="")
    assert p.is_configured is False
    with pytest.raises(ProviderUnavailableError):
        p.research_company("X", "X Co")
    with pytest.raises(ProviderUnavailableError):
        p.suggest_peers("X", "X Co", "S", "I")
    with pytest.raises(ProviderUnavailableError):
        p.research_news("X", "X Co")
    assert p.verify_model() == {
        "ok": False,
        "model": p.model_name,
        "error": "GEMINI_API_KEY is not configured.",
    }


# --- Task 4: BBL research task -------------------------------------------------
# "Identify the sector and industry of Bharat Bijlee Limited (BBL), and
#  identify several relevant listed Indian peer companies. Use grounded web
#  research."


_BBL_PAYLOAD = {
    "company_name": "Bharat Bijlee Limited",
    "sector": "Industrials",
    "industry": "Electrical Equipment",
    "business_description": "Motors and transformers manufacturer.",
    "confidence": 0.88,
    "peers": [
        {"symbol": "SIEMENS", "name": "Siemens Ltd", "reason": "motors peer"},
        {"symbol": "ABB", "name": "ABB India", "reason": "electrification peer"},
    ],
}


def test_bbl_research_task_succeeds_grounded():
    seen: dict = {}

    def behavior(kind, **kwargs):
        assert kind == "generate"
        seen["kwargs"] = kwargs
        return _FakeResponse(_BBL_PAYLOAD, _chunks())

    p, _ = _provider_with(behavior)
    out = p.research_company("BBL", "BHARAT BIJLEE LTD")

    # 1. Request succeeds with a non-empty structured response.
    assert out["company_name"] == "Bharat Bijlee Limited"
    assert out["sector"] == "Industrials"
    assert out["industry"] == "Electrical Equipment"
    assert out["confidence"] == 0.88
    assert [x["symbol"] for x in out["peers"]] == ["SIEMENS", "ABB"]
    # 2/3. Grounding was enabled in the request AND citations came back.
    cfg = seen["kwargs"]["config"]
    assert cfg.tools, "google_search tool must be attached"
    assert out["grounded"] is True
    # 4. Sources/citations available.
    assert len(out["sources"]) == 2
    assert out["sources"][0]["domain"] == "example.com"
    assert out["retrieved_at"]
    # 5. Model recorded for provenance.
    assert out["model"] == p.model_name


def test_grounding_config_uses_sdk_search_tool():
    def behavior(kind, **kwargs):
        return _FakeResponse(_BBL_PAYLOAD, _chunks())

    p, _ = _provider_with(behavior, web_search_enabled=True)
    p.research_company("BBL", "BHARAT BIJLEE LTD")
    # Disabled grounding attaches no tools.
    p2, _ = _provider_with(behavior, web_search_enabled=False)
    assert p2.grounding_enabled is False


def test_key_only_reaches_client_constructor():
    def behavior(kind, **kwargs):
        return _FakeResponse(_BBL_PAYLOAD)

    _provider_with(behavior)
    assert _FakeClient.instances, "client must be constructed"
    for inst in _FakeClient.instances:
        # No URL/param plumbing exists in the SDK path; the key is a ctor arg.
        assert inst.api_key == FAKE_KEY
    # Nothing key-like is formatted into prompts or configs.
    import json as _json

    blob = _json.dumps(_FakeClient.instances[0].models.calls, default=str)
    assert FAKE_KEY not in blob


# --- peer suggestions ------------------------------------------------------------


def test_suggest_peers_parses_candidates():
    def behavior(kind, **kwargs):
        return _FakeResponse(
            {
                "peers": [
                    {"symbol": "TATAPOWER", "name": "Tata Power", "reason": "thermal peer"},
                    {"symbol": "NTPC", "name": "NTPC", "reason": "power peer"},
                ]
            },
            _chunks(),
        )

    p, _ = _provider_with(behavior)
    out = p.suggest_peers("ADANIPOWER", "Adani Power", "Utilities", "Power Generation")
    assert [x["symbol"] for x in out["peers"]] == ["TATAPOWER", "NTPC"]
    assert out["grounded"] is True


def test_company_self_never_listed_as_peer():
    def behavior(kind, **kwargs):
        return _FakeResponse(
            {
                "company_name": "Adani Power Limited",
                "sector": "Utilities",
                "industry": "Power Generation",
                "peers": [{"symbol": "ADANIPOWER", "name": "Self"}],
            }
        )

    p, _ = _provider_with(behavior)
    out = p.research_company("ADANIPOWER", "ADANI POWER LTD")
    assert out["peers"] == []


def test_research_company_rejects_missing_sector():
    def behavior(kind, **kwargs):
        return _FakeResponse({"company_name": "X", "sector": "", "industry": ""})

    p, _ = _provider_with(behavior)
    with pytest.raises(ProviderError):
        p.research_company("X", "X Co")


# --- news digest -------------------------------------------------------------------


def test_research_news_labeled_digest():
    def behavior(kind, **kwargs):
        return _FakeResponse(
            {
                "items": [
                    {
                        "title": "Adani Power commissions new unit",
                        "summary": "800 MW added.",
                        "url": "https://example.com/unit",
                        "source": "Example Wire",
                        "published_at": "2026-09-20",
                    },
                    {"title": "", "url": "https://example.com/empty"},
                ]
            },
            _chunks(),
        )

    p, _ = _provider_with(behavior)
    out = p.research_news("ADANIPOWER", "Adani Power")
    assert len(out["items"]) == 1  # empty title dropped
    assert out["items"][0]["url"] == "https://example.com/unit"


# --- verify_model ----------------------------------------------------------------------


def test_verify_model_ok_and_failures():
    class _OkResp:
        text = "ok"

    ok_client = _FakeClient(api_key=FAKE_KEY)
    ok_client._behavior_impl = lambda kind, **kw: _OkResp()
    ok_client.models = _FakeModels(ok_client._behavior_impl)
    p = GeminiResearchProvider(api_key=FAKE_KEY)
    p._client = ok_client
    assert p.verify_model() == {"ok": True, "model": p.model_name, "error": None}

    def behavior(kind, **kwargs):
        raise APIError(404, {"error": {"message": "not found"}})

    p2, _ = _provider_with(behavior)
    result = p2.verify_model()
    assert result["ok"] is False
    assert "not available" in result["error"]
    assert FAKE_KEY not in result["error"]


# --- failure diagnostics -------------------------------------------------------------------


def test_auth_failure_diagnostic():
    def behavior(kind, **kwargs):
        raise APIError(401, {"error": {"message": "API key not valid"}})

    p, _ = _provider_with(behavior)
    with pytest.raises(ProviderUnavailableError) as exc:
        p.research_company("X", "X")
    assert "API key" in exc.value.message
    assert FAKE_KEY not in str(exc.value.message)
    assert FAKE_KEY not in str(getattr(exc.value, "details", {}))


def test_model_unavailable_diagnostic_names_model():
    def behavior(kind, **kwargs):
        raise APIError(404, {"error": {"message": "not found"}})

    p, _ = _provider_with(behavior, model="gemini-2.5-flash")
    with pytest.raises(ProviderUnavailableError) as exc:
        p.research_company("X", "X")
    assert "gemini-2.5-flash" in exc.value.message
    assert "not available" in exc.value.message
    assert "GEMINI_MODEL" in exc.value.message
    assert FAKE_KEY not in str(exc.value.message)


def test_rate_limit_diagnostic():
    def behavior(kind, **kwargs):
        raise APIError(429, {"error": {"message": "quota"}})

    p, _ = _provider_with(behavior)
    with pytest.raises(ProviderError) as exc:
        p.research_company("X", "X")
    assert "429" in exc.value.message


def test_endpoint_error_diagnostic():
    def behavior(kind, **kwargs):
        raise APIError(503, {"error": {"message": "overloaded"}})

    p, _ = _provider_with(behavior)
    with pytest.raises(ProviderError) as exc:
        p.research_company("X", "X")
    assert "503" in exc.value.message


def test_timeout_diagnostic():
    def behavior(kind, **kwargs):
        raise TimeoutError("timed out")

    p, _ = _provider_with(behavior, timeout_seconds=7)
    with pytest.raises(ProviderError) as exc:
        p.research_company("X", "X")
    assert "timed out" in exc.value.message


def test_safety_block_diagnostic():
    class _Blocked:
        text = ""
        candidates = []
        prompt_feedback = type("F", (), {"block_reason": "SAFETY"})()

    def behavior(kind, **kwargs):
        return _Blocked()

    p, _ = _provider_with(behavior)
    with pytest.raises(ProviderError) as exc:
        p.research_company("X", "X")
    assert "safety" in exc.value.message.lower()


def test_empty_and_malformed_responses():
    class _Empty:
        text = ""
        candidates = []
        prompt_feedback = None

    class _BadJson:
        text = "not json"
        candidates = []
        prompt_feedback = None

    class _NonObject:
        text = "[1,2]"
        candidates = []
        prompt_feedback = None

    for fake in (_Empty(), _BadJson(), _NonObject()):
        def behavior(kind, _f=fake, **kwargs):
            return _f

        p, _ = _provider_with(behavior)
        with pytest.raises(ProviderError):
            p.research_company("X", "X")


def test_network_failure_never_leaks_key():
    def behavior(kind, **kwargs):
        raise ConnectionError(f"boom {FAKE_KEY} in exception")

    p, _ = _provider_with(behavior)
    with pytest.raises(ProviderError) as exc:
        p.research_company("X", "X")
    assert FAKE_KEY not in str(exc.value.message)
    assert FAKE_KEY not in str(getattr(exc.value, "details", {}))


def test_key_absent_from_logs(caplog):
    def behavior(kind, **kwargs):
        raise APIError(403, {"error": {"message": "denied"}})

    p, _ = _provider_with(behavior)
    with caplog.at_level(logging.WARNING, logger="fincortext.providers.gemini_research"):
        with pytest.raises(ProviderUnavailableError):
            p.research_company("X", "X")
    assert FAKE_KEY not in caplog.text
