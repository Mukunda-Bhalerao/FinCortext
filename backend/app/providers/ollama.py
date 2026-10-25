"""Optional local language model (Ollama) used only to phrase rationales from given evidence."""

import httpx

from app.errors import ProviderUnavailable


class OllamaClient:
    def __init__(self, base_url: str, model: str):
        self.model = model
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=60.0)

    async def generate(self, prompt: str) -> str:
        try:
            resp = await self._client.post(
                "/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0},
                },
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderUnavailable("The local language model is not reachable.") from exc
        return str((resp.json() or {}).get("response") or "").strip()

    async def aclose(self) -> None:
        await self._client.aclose()
