"""Unit tests for dashboard.backend.static's try_files-style resolution
(PRD §13 — pip-installable dashboard). No live server, no built frontend
needed — this builds a throwaway fake `out/` directory per test.

Requires the `dashboard` extra (same reason as test_dashboard_backend.py).
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from dashboard.backend import static  # noqa: E402


def _out(tmp_path: Path) -> Path:
    out = tmp_path / "out"
    out.mkdir()
    return out


def test_root_path_resolves_to_index_html(tmp_path: Path) -> None:
    out = _out(tmp_path)
    (out / "index.html").write_text("root")
    result = static.resolve_static_file("", root=out)
    assert result == out / "index.html"


def test_exact_file_match_wins_first(tmp_path: Path) -> None:
    out = _out(tmp_path)
    (out / "_next").mkdir()
    (out / "_next" / "chunk.js").write_text("js")
    result = static.resolve_static_file("_next/chunk.js", root=out)
    assert result == out / "_next" / "chunk.js"


def test_pretty_url_resolves_to_html_sibling(tmp_path: Path) -> None:
    out = _out(tmp_path)
    (out / "apps.html").write_text("apps page")
    result = static.resolve_static_file("apps", root=out)
    assert result == out / "apps.html"


def test_trailing_slash_style_directory_index(tmp_path: Path) -> None:
    out = _out(tmp_path)
    (out / "apps").mkdir()
    (out / "apps" / "index.html").write_text("apps index")
    result = static.resolve_static_file("apps", root=out)
    # apps.html doesn't exist, so this falls through to apps/index.html.
    assert result == out / "apps" / "index.html"


def test_unmatched_path_returns_none(tmp_path: Path) -> None:
    out = _out(tmp_path)
    (out / "index.html").write_text("root")
    assert static.resolve_static_file("nope/nothing-here", root=out) is None


def test_path_traversal_outside_root_is_refused(tmp_path: Path) -> None:
    out = _out(tmp_path)
    secret = tmp_path / "secret.txt"
    secret.write_text("do not serve me")
    # FastAPI's path converter already normalizes "..", but this exercises
    # the defensive check directly regardless of what the router allows through.
    assert static.resolve_static_file("../secret.txt", root=out) is None


def test_serve_static_returns_404_html_when_nothing_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = _out(tmp_path)
    (out / "404.html").write_text("not found page")
    monkeypatch.setattr(static, "FRONTEND_OUT_DIR", out)

    app = FastAPI()
    app.include_router(static.router)
    client = TestClient(app)
    resp = client.get("/does-not-exist")
    assert resp.status_code == 404
    assert resp.text == "not found page"


def test_serve_static_serves_matched_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = _out(tmp_path)
    (out / "index.html").write_text("hello dashboard")
    monkeypatch.setattr(static, "FRONTEND_OUT_DIR", out)

    app = FastAPI()
    app.include_router(static.router)
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.text == "hello dashboard"
