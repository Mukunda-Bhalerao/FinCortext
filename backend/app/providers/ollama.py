"""Optional language model through an Ollama server: a local model, or a cloud model routed
by a signed-in local Ollama (for example ``gpt-oss:120b-cloud``), or ollama.com directly with
an API key. Used only to phrase and explain evidence that the deterministic engine produced."""

import json
from collections.abc import Callable

import httpx

from app.errors import ProviderUnavailable, RateLimited


def _json_object(text: str) -> dict | None:
    """The JSON object in ``text``, also when the model wraps it in prose or code fences."""
    for candidate in (text, text[text.find("{") : text.rfind("}") + 1] if "{" in text else ""):
        if not candidate:
            continue
        try:
            value = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return None


class OllamaClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        timeout: float = 60.0,
        before: Callable[[], None] | None = None,
        after: Callable[[str, int, int], None] | None = None,
    ):
        """``before`` may raise to refuse a call (usage budget); ``after`` receives
        (purpose, prompt tokens, output tokens) for each completed call."""
        self.model = model
        self._before = before
        self._after = after
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"), timeout=timeout, headers=headers
        )

    async def _post(self, path: str, body: dict, purpose: str = "other") -> dict:
        if self._before is not None:
            self._before()
        try:
            resp = await self._client.post(path, json=body)
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(
                "The language model is not reachable; check that Ollama is running."
            ) from exc
        if resp.status_code == 429:
            raise RateLimited("The language model's usage limit was reached; try again later.")
        if resp.status_code != 200:
            raise ProviderUnavailable(f"The language model returned HTTP {resp.status_code}.")
        data = resp.json() or {}
        if self._after is not None:
            self._after(
                purpose, int(data.get("prompt_eval_count") or 0), int(data.get("eval_count") or 0)
            )
        return data

    async def generate(self, prompt: str, purpose: str = "rationale") -> str:
        data = await self._post(
            "/api/generate",
            {"model": self.model, "prompt": prompt, "stream": False, "options": {"temperature": 0}},
            purpose,
        )
        return str(data.get("response") or "").strip()

    async def chat_json(self, system: str, messages: list[dict], purpose: str = "chat") -> dict:
        """One chat turn constrained to a JSON object; raises ProviderUnavailable if the model
        does not return valid JSON."""
        data = await self._post(
            "/api/chat",
            {
                "model": self.model,
                "messages": [{"role": "system", "content": system}, *messages],
                "stream": False,
                "format": "json",
                "options": {"temperature": 0},
            },
            purpose,
        )
        text = str((data.get("message") or {}).get("content") or "").strip()
        parsed = _json_object(text)
        if parsed is None:
            raise ProviderUnavailable("The language model returned malformed output.")
        return parsed

    async def aclose(self) -> None:
        await self._client.aclose()
