from __future__ import annotations

from pathlib import Path


def test_collection_page_serves_built_desktop_console_when_dist_exists(monkeypatch, tmp_path) -> None:
    from src import server

    dist = tmp_path / "collector-desktop" / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text('<div id="app">built console</div>', encoding="utf-8")
    (assets / "index-test.js").write_text('console.log("built console")', encoding="utf-8")
    monkeypatch.setattr(server, "COLLECTOR_DESKTOP_DIST", dist)

    assert server._collection_observer_page_html() == '<div id="app">built console</div>'
    asset = server._collection_observer_static_asset("/collection/assets/index-test.js")
    assert asset is not None
    assert asset[0] == b'console.log("built console")'
    assert asset[1] == "application/javascript"
    root_asset = server._collection_observer_static_asset("/assets/index-test.js")
    assert root_asset is not None
    assert root_asset[0] == b'console.log("built console")'
    assert root_asset[1] == "application/javascript"


def test_collection_page_falls_back_to_inline_console_when_dist_missing(monkeypatch, tmp_path) -> None:
    from src import server

    monkeypatch.setattr(server, "COLLECTOR_DESKTOP_DIST", tmp_path / "missing")

    html = server._collection_observer_page_html()

    assert "FapaiFang 采集观察台" in html
    assert "/api/collection/overview" in html
