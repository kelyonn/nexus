#!/usr/bin/env python3
"""Generate dashboard/frontend/lib/api.generated.ts from the dashboard
backend's Pydantic response models — the single source of truth for the
API's shape, so the frontend's types can't silently drift from what
dashboard/backend/routes.py actually returns. This was a real, repeated
problem while building the dashboard: has_http_metrics, created_at, and
subject each needed adding by hand to both routes.py *and* api.ts.

Usage:
    python3 scripts/generate_dashboard_types.py

Needs this repo's venv (with the `dashboard` extra —
``pip install -e ".[dashboard]"``) and Node (``npm install`` in
dashboard/frontend, for json-schema-to-typescript). CI
(.github/workflows/ci.yml's dashboard-frontend job) runs this and fails the
build if the committed output is stale relative to routes.py.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = REPO_ROOT / "dashboard" / "frontend"
OUTPUT_PATH = FRONTEND_DIR / "lib" / "api.generated.ts"

# An editable install (`pip install -e .`) only keeps `packages` (nexus_cli)
# live-linked to source — `dashboard`, added via pyproject.toml's
# `force-include` (see that file's comment), gets physically snapshotted
# into site-packages once at install time and does NOT track further edits.
# Left alone, whichever copy sys.path happens to resolve first "wins",
# which is exactly the kind of stale-import bug this script exists to
# prevent in the first place. Inserting REPO_ROOT first guarantees this
# script always reads the real, current source, regardless of what's (or
# isn't) sitting in site-packages.
sys.path.insert(0, str(REPO_ROOT))

# Every Pydantic model the dashboard API returns or accepts as a request
# body (dashboard/backend/routes.py). Deliberately not auto-discovered —
# forgetting to add a new model here shows up as a visible, reviewable diff
# in this file instead of silently generating nothing for it.
MODEL_NAMES = [
    "AppSummary",
    "PodSummary",
    "ChaosRequest",
    "ChaosResponse",
    "SyncEventOut",
    "SyncLogResponse",
    "MetricPoint",
    "MetricsResponse",
]

HEADER = """\
/**
 * GENERATED FILE — do not edit by hand.
 *
 * Regenerate with `python3 scripts/generate_dashboard_types.py` after
 * changing a Pydantic model in dashboard/backend/routes.py. CI fails if
 * this file is stale relative to those models (see
 * .github/workflows/ci.yml's dashboard-frontend job).
 */

"""


def _strip_titles(obj: object) -> None:
    """Pydantic puts a ``title`` on every field's schema, which makes
    json-schema-to-typescript hoist each field into its own named type
    alias (``Name``, ``Name1``, ...) instead of inlining it inline —
    stripping titles everywhere keeps the generated interfaces readable.
    """
    if isinstance(obj, dict):
        obj.pop("title", None)
        for v in obj.values():
            _strip_titles(v)
    elif isinstance(obj, list):
        for v in obj:
            _strip_titles(v)


def _build_schema() -> dict[str, object]:
    from pydantic.json_schema import models_json_schema

    from dashboard.backend import routes

    models = [getattr(routes, name) for name in MODEL_NAMES]
    _, schema = models_json_schema([(m, "serialization") for m in models])
    _strip_titles(schema)
    return schema


def _run_json2ts(schema: dict[str, object]) -> str:
    result = subprocess.run(
        ["npx", "json2ts", "--unreachableDefinitions", "--no-additionalProperties"],
        input=json.dumps(schema),
        capture_output=True,
        text=True,
        cwd=FRONTEND_DIR,
    )
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        raise SystemExit("json2ts failed — see stderr above.")
    return result.stdout


def _drop_json2ts_header(body: str) -> str:
    """json-schema-to-typescript prepends its own `/* eslint-disable */`
    plus a file-header doc comment — drop both; ``HEADER`` above replaces
    them with a header that actually says how to regenerate this file.
    """
    marker = "export interface"
    start = body.find(marker)
    if start == -1:
        raise SystemExit(f"Expected to find {marker!r} in json2ts output — output shape changed?")
    return body[start:].strip()


_REFERENCED_BY_COMMENT = re.compile(
    r"/\*\*\n \* This interface was referenced by `undefined`'s JSON-Schema\n"
    r' \* via the `definition` "\w+"\.\n \*/\n'
)


def _drop_referenced_by_comments(body: str) -> str:
    """Each interface (except the first) gets a
    "referenced by `undefined`'s JSON-Schema" comment — `undefined` because
    our schema's root has no title (it only exists to hold $defs). Not
    useful information; drop it rather than ship a file full of
    `undefined` references.
    """
    return _REFERENCED_BY_COMMENT.sub("", body)


def main() -> None:
    schema = _build_schema()
    raw = _run_json2ts(schema)
    body = _drop_json2ts_header(raw)
    body = _drop_referenced_by_comments(body)
    OUTPUT_PATH.write_text(HEADER + body + "\n")
    print(f"Wrote {OUTPUT_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
