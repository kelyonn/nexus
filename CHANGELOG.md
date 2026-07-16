# Changelog

All notable changes to Nexus are documented here. Format based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this project follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Python package skeleton: `pyproject.toml` (hatchling, `nexus-platform`, entry
  point `nexus = nexus_cli.main:app`), Typer app with `--version`/`--help`,
  Apache-2.0 license, and the tooling config for `ruff`, `mypy`, and `pytest`.
