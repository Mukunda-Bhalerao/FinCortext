"""Serve the built interface from the API process.

In development Vite serves the interface on its own port and proxies /api here. In a
deployment there is one container: the built files sit next to the backend and this module
serves them, so there is a single origin and no CORS. When no build is present (a developer
running only the backend) the app still starts and only the API responds.
"""

import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

log = logging.getLogger(__name__)

CACHE_FOREVER = "public, max-age=31536000, immutable"  # hashed asset file names
# STATIC_DIR is set by the Dockerfile. The rest are for a source checkout, where the package
# may be imported from the repository or from site-packages, so neither path is guaranteed.
CANDIDATES = tuple(
    p
    for p in (
        Path(os.environ["STATIC_DIR"]) if os.environ.get("STATIC_DIR") else None,
        Path(__file__).resolve().parents[2] / "static",
        Path(__file__).resolve().parents[3] / "frontend" / "dist",
        Path.cwd() / "static",
        Path.cwd() / "frontend" / "dist",
    )
    if p is not None
)


def find_build() -> Path | None:
    return next((p for p in CANDIDATES if (p / "index.html").is_file()), None)


class HashedAssets(StaticFiles):
    """The build gives every asset a content hash in its name, so a file at a given path never
    changes and the browser can keep it."""

    def is_not_modified(self, response_headers, request_headers) -> bool:
        response_headers["cache-control"] = CACHE_FOREVER
        return super().is_not_modified(response_headers, request_headers)

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["cache-control"] = CACHE_FOREVER
        return response


def mount(app: FastAPI) -> bool:
    """Serve the built interface. Returns False when there is nothing to serve."""
    root = find_build()
    if root is None:
        log.info("no interface build found; serving the API only")
        return False
    index = root / "index.html"

    assets = root / "assets"
    if assets.is_dir():
        app.mount("/assets", HashedAssets(directory=assets), name="assets")

    @app.get("/{path:path}", include_in_schema=False, response_model=None)
    async def spa(path: str) -> FileResponse | JSONResponse:
        """Any path that is not an API route: a real file if there is one, otherwise the
        single page, so a deep link such as /portfolios/abc opens correctly on reload."""
        if path.startswith(("api/", "api")) and path not in ("api", "api/"):
            return JSONResponse(
                {"error": {"code": "not_found", "message": "No such endpoint."}}, 404
            )
        candidate = (root / path).resolve()
        if path and root in candidate.parents and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    log.info("serving the interface from %s", root)
    return True
