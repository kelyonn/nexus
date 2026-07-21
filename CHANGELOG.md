# Changelog

All notable changes to Nexus are documented here. Format based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this project follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Python package skeleton: `pyproject.toml` (hatchling, `nexus-platform`, entry
  point `nexus = nexus_cli.main:app`), Typer app with `--version`/`--help`,
  Apache-2.0 license, and the tooling config for `ruff`, `mypy`, and `pytest`.
- `nexus.yaml` config schema (Pydantic v2) with full validation per spec, and
  stack detection (Node, Flask, generic) for `nexus init`.
- `nexus init` — detects your stack, prompts for image/repo/branch, writes a
  pre-filled `nexus.yaml`.
- Jinja2 manifest templates (namespace, deployment, service, ArgoCD
  application, Prometheus rules, Grafana dashboard, chaos schedule) and the
  render pipeline that fills them in from `nexus.yaml`.
- `nexus status` and `nexus watch` — deployment health, ArgoCD sync/health,
  ImagePullBackOff/CrashLoopBackOff detection with a context-aware fix, and
  live pod events.
- `nexus deploy` and `nexus destroy` — install missing platform components via
  Helm, apply manifests, sync them to git so ArgoCD can reach `Synced`,
  register the ArgoCD application, and verify; `destroy` removes only the
  app's own resources behind a typed-name confirmation. Both idempotent.
- `examples/flask-demo/` — a working example promoted from the archived demo,
  used as the render golden-test fixture and for live cluster verification.

### Fixed
- `nexus deploy` now commits and pushes rendered manifests to the tracked git
  repo before registering the ArgoCD application, so `sync` can actually reach
  `Synced` on a first deploy (previously it never wrote to git, so ArgoCD had
  nothing valid to compare against).
- `git.current_branch()` no longer misreports the branch as unset on a
  repository that has no commits yet.
