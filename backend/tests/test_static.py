"""Serving the built interface from the API process (how a deployment runs).

These guard the two failures that only show up once deployed: a deep link reloading into a
404, and an unknown API path answering with the HTML page instead of a JSON error.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import static

INDEX = "<!doctype html><html><body><div id='root'></div></body></html>"


def _build(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "index.html").write_text(INDEX, encoding="utf-8")
    (tmp_path / "logo-mark.png").write_bytes(b"\x89PNG\r\n")
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "index-abc123.js").write_text("console.log(1)", encoding="utf-8")
    return tmp_path


def _app(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setattr(static, "CANDIDATES", (_build(tmp_path),))
    app = FastAPI()

    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "ok"}

    assert static.mount(app) is True
    return TestClient(app)


def test_api_routes_still_win_over_the_page(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch)
    assert client.get("/api/health").json() == {"status": "ok"}


def test_unknown_api_path_is_json_not_the_page(tmp_path, monkeypatch):
    resp = _app(tmp_path, monkeypatch).get("/api/does-not-exist")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_deep_links_load_the_page_so_reloads_work(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch)
    for path in ("/", "/portfolios/abc123", "/stock/RELIANCE", "/lab"):
        resp = client.get(path)
        assert resp.status_code == 200, path
        assert "id='root'" in resp.text, path
        assert resp.headers["cache-control"] == "no-cache", path


def test_real_files_are_served_and_hashed_assets_are_cached(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch)
    asset = client.get("/assets/index-abc123.js")
    assert asset.status_code == 200
    assert asset.headers["cache-control"] == static.CACHE_FOREVER
    assert client.get("/logo-mark.png").content.startswith(b"\x89PNG")


def test_paths_outside_the_build_are_refused(tmp_path, monkeypatch):
    """A traversal attempt falls back to the page rather than reading the filesystem."""
    secret = tmp_path.parent / "secret.txt"
    secret.write_text("private", encoding="utf-8")
    resp = _app(tmp_path / "dist", monkeypatch).get("/../secret.txt")
    assert "private" not in resp.text


def test_without_a_build_the_api_still_starts(tmp_path, monkeypatch):
    monkeypatch.setattr(static, "CANDIDATES", (tmp_path / "missing",))
    app = FastAPI()
    assert static.mount(app) is False


def test_static_dir_env_var_wins(tmp_path, monkeypatch):
    """The container sets STATIC_DIR, so serving never depends on where Python imported the
    package from (the repository or site-packages)."""
    import importlib

    _build(tmp_path / "build")
    monkeypatch.setenv("STATIC_DIR", str(tmp_path / "build"))
    reloaded = importlib.reload(static)
    try:
        assert reloaded.CANDIDATES[0] == tmp_path / "build"
        assert reloaded.find_build() == tmp_path / "build"
    finally:
        monkeypatch.delenv("STATIC_DIR", raising=False)
        importlib.reload(static)
