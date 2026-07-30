#!/usr/bin/env python3
"""Verify every internal link in the built docs site resolves.

`mkdocs build --strict` only validates links written in **markdown**. The
homepage is rendered by a Jinja template (overrides/home.html), so its links —
the nav, the command-reference pointers, the CTA buttons — are invisible to
that check. This script closes the gap by walking the *built* HTML in `site/`,
which is what visitors actually get.

Checks, for every `href`/`src` in every built page:

* internal page/asset links resolve to a real file in `site/`
* `#fragment` targets exist as an `id=` (or `name=`) on the target page

Skips external URLs (http/https/mailto/tel) — those are not this repo's to
guarantee, and hitting the network would make CI flaky.

Usage:
    mkdocs build --strict && python scripts/check_links.py
"""

from __future__ import annotations

import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
SITE_DIR = REPO_ROOT / "site"
MKDOCS_YML = REPO_ROOT / "mkdocs.yml"

# Attributes that carry a URL we should resolve.
URL_ATTRS = {"href", "src"}

SKIP_SCHEMES = {"http", "https", "mailto", "tel", "data", "javascript"}


class LinkCollector(HTMLParser):
    """Collects (url, id) pairs from a built HTML page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.urls: list[str] = []
        self.ids: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {k: v for k, v in attrs if v is not None}
        for key in URL_ATTRS:
            if key in attr_map:
                self.urls.append(attr_map[key])
        # Anchor targets can be either id= (modern) or name= (legacy).
        for key in ("id", "name"):
            if key in attr_map:
                self.ids.add(attr_map[key])


def site_base_path() -> str:
    """The URL path `site/` is served from, per mkdocs.yml's `site_url`.

    GitHub Pages serves this project from `https://<user>.github.io/nexus/`,
    so MkDocs' generated 404.html (which must work at any depth) emits
    root-absolute links like `/nexus/install/`. Stripping this prefix maps
    those back onto the local `site/` tree.
    """
    if not MKDOCS_YML.exists():
        return "/"
    for line in MKDOCS_YML.read_text(encoding="utf-8").splitlines():
        if line.startswith("site_url:"):
            url = line.split(":", 1)[1].strip()
            path = urlparse(url).path
            return path if path.endswith("/") else path + "/"
    return "/"


BASE_PATH = site_base_path()


def parse_page(path: Path) -> LinkCollector:
    collector = LinkCollector()
    collector.feed(path.read_text(encoding="utf-8", errors="replace"))
    return collector


def resolve(page: Path, url: str) -> Path | None:
    """Map a URL found on `page` to the file in site/ it should point at.

    Returns None when the link is external or otherwise not ours to check.
    """
    parsed = urlparse(url)
    if parsed.scheme in SKIP_SCHEMES or parsed.netloc:
        return None

    path_part = unquote(parsed.path)
    if not path_part:  # pure "#anchor" — same page
        return page

    if path_part.startswith("/"):
        # Root-absolute (MkDocs' 404.html uses these). Strip the deployed base
        # path — "/nexus/install/" is "install/" inside site/.
        if BASE_PATH != "/" and path_part.startswith(BASE_PATH):
            path_part = path_part[len(BASE_PATH) :]
        elif BASE_PATH != "/" and path_part.rstrip("/") == BASE_PATH.rstrip("/"):
            path_part = ""
        else:
            path_part = path_part.lstrip("/")
        target = SITE_DIR / path_part if path_part else SITE_DIR
    else:
        target = (page.parent / path_part).resolve()

    if target.is_dir():
        target = target / "index.html"
    elif not target.suffix:
        # e.g. "install/" already handled above; a bare extensionless path.
        candidate = target / "index.html"
        if candidate.exists():
            target = candidate
    return target


def main() -> int:
    if not SITE_DIR.exists():
        print(f"error: {SITE_DIR} not found — run `mkdocs build` first.", file=sys.stderr)
        return 2

    pages = sorted(SITE_DIR.rglob("*.html"))
    if not pages:
        print(f"error: no HTML found under {SITE_DIR}.", file=sys.stderr)
        return 2

    # Anchor ids per built page, parsed once.
    page_ids: dict[Path, set[str]] = {}
    page_urls: dict[Path, list[str]] = {}
    for page in pages:
        collected = parse_page(page)
        page_ids[page] = collected.ids
        page_urls[page] = collected.urls

    problems: list[str] = []
    checked = 0

    for page in pages:
        rel_page = page.relative_to(SITE_DIR)
        for url in page_urls[page]:
            target = resolve(page, url)
            if target is None:
                continue
            checked += 1

            if not target.exists():
                problems.append(f"{rel_page}: -> {url} (no such file: {target.name})")
                continue

            fragment = urlparse(url).fragment
            if not fragment:
                continue
            # Only HTML pages have anchors worth checking.
            if target.suffix != ".html":
                continue
            ids = page_ids.get(target)
            if ids is None:
                ids = parse_page(target).ids
                page_ids[target] = ids
            if unquote(fragment) not in ids:
                problems.append(f"{rel_page}: -> {url} (no #{fragment} on target page)")

    print(f"checked {checked} internal links across {len(pages)} built pages")
    if problems:
        print(f"\n{len(problems)} broken link(s):\n", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1

    print("all internal links resolve")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
