"""Retrying GET for public data sources: transient network errors and 429/5xx answers are
retried twice with a short backoff before the caller sees the failure."""

import asyncio

import httpx

RETRY_STATUS = {429, 500, 502, 503, 504}
BACKOFF = (0.5, 1.5)


async def get(client: httpx.AsyncClient, url: str, **kwargs) -> httpx.Response:
    for delay in (*BACKOFF, None):
        try:
            resp = await client.get(url, **kwargs)
        except httpx.TransportError:
            if delay is None:
                raise
        else:
            if resp.status_code not in RETRY_STATUS or delay is None:
                return resp
        await asyncio.sleep(delay)
    raise AssertionError("unreachable")
