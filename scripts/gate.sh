#!/usr/bin/env bash
# The one quality gate CI's lint-and-unit job, the release workflow, and
# CONTRIBUTING.md all invoke — extracted so "does what release checks match
# what CI checks" has one answer instead of three independently-maintained
# ones. Before this existed, they'd already diverged: the release workflow
# installed `.[dev]` only (so the dashboard's tests silently no-op'd via
# `pytest.importorskip("fastapi")`), type-checked `nexus_cli` alone even
# though pyproject.toml's own `[tool.mypy]` also lists `dashboard/backend`,
# and ran bare `pytest -q` with no coverage floor at all — on the one path
# that actually reaches PyPI.
#
# Assumes `pip install -e ".[dev,dashboard]"` has already run — installing
# dependencies is left to the caller since a fresh CI job and a local dev
# venv reasonably do that differently (caching, etc).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

ruff check .
mypy nexus_cli dashboard/backend
pytest -q --cov=nexus_cli --cov-report=term-missing --cov-fail-under=90
