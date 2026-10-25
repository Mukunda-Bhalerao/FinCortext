"""Optional language model through an Ollama server: a local model, or a cloud model routed
by a signed-in local Ollama (for example ``gpt-oss:120b-cloud``), or ollama.com directly with
an API key. Used only to phrase and explain evidence that the deterministic engine produced."""

import json

import httpx

from app.errors import ProviderUnavailable, RateLimited


class OllamaClient:
    def __init__(self, base_url: str, model: str, api_key: str = "", timeout: float = 60.0):
        self.model = model
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"), timeout=timeout, headers=headers
        )

    async def _post(self, path: str, body: dict) -> dict:
        try:
            resp = await self._client.post(path, json=body)
        except httpx.HTTPError as exc:
            raise ProviderUnavailable("The language model is not reachable.") from exc
        if resp.status_code == 429:
            raise RateLimited("The language model's usage limit was reached; try again later.")
        if resp.status_code != 200:
            raise ProviderUnavailable(f"The language model returned HTTP {resp.status_code}.")
        return resp.json() or {}

    async def generate(self, prompt: str) -> str:
        data = await self._post(
            "/api/generate",
            {"model": self.model, "prompt": prompt, "stream": False, "options": {"temperature": 0}},
        )
        return str(data.get("response") or "").strip()

    async def chat_json(self, system: str, messages: list[dict]) -> dict:
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
        )
        text = str((data.get("message") or {}).get("content") or "").strip()
        try:
            parsed = json.loads(text)
        except ValueError as exc:
            raise ProviderUnavailable("The language model returned malformed output.") from exc
        if not isinstance(parsed, dict):
            raise ProviderUnavailable("The language model returned malformed output.")
        return parsed

    async def aclose(self) -> None:
        await self._client.aclose()
