# Changelog

All notable changes to Nexus are documented here. Format based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this project follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Python package skeleton: `pyproject.toml` (hatchling, `nexus-gitops`, entry
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
- `nexus logs` — prints each pod's log tail (`--tail`, default 50 lines),
  prefixed with the pod name.
- `nexus chaos run` — one-shot PodChaos experiment (`--kill-all`, `--action`),
  reports which pod(s) were killed and confirms recovery; `nexus chaos
  schedule enable`/`disable` manage the recurring schedule via Chaos Mesh's
  pause annotation (there's no spec field for it) and report current status.
- `nexus doctor` — environment diagnostics: kubectl/helm/cluster reachability,
  RBAC (`kubectl auth can-i create namespaces/deployments`), `nexus.yaml`
  presence and validity (full field-level errors, not just "invalid"), git
  repo/branch/remote sanity against `platform.branch`/`repoURL`, and installed
  status for ArgoCD/kube-prometheus-stack/Chaos Mesh. Runs every check
  regardless of earlier failures and reports all problems in one pass; exits
  non-zero if any check failed.
- `nexus upgrade` — bumps `app.image` (regex edit, preserves comments/
  formatting), re-renders + commits `k8s/` alongside `nexus.yaml` (ArgoCD
  reconciles from `k8s/`, not `nexus.yaml` — see `core/gitops.py`), commits +
  pushes, triggers an explicit ArgoCD sync, and reports the rolled-out pods.
  Safety checks (clean tree, git repo, branch match, remote configured) per
  PRD §7.9; `--dry-run` and `--yes`.
- `nexus rollback` — GitOps-correct rollback through git, never ArgoCD's own
  revision rollback (self-heal would immediately undo that). Default `git
  revert`s the most recent nexus-authored image commit; `--to-commit <sha>`
  restores an arbitrary historical state; `--list` shows recent image changes
  (works without a cluster). `core/gitops.py`/`core/git.py` are shared with
  `upgrade` (git primitives, image-in-YAML editing, the commit/push/sync/wait
  tail).

### Fixed
- `nexus deploy` now commits and pushes rendered manifests to the tracked git
  repo before registering the ArgoCD application, so `sync` can actually reach
  `Synced` on a first deploy (previously it never wrote to git, so ArgoCD had
  nothing valid to compare against).
- `git.current_branch()` no longer misreports the branch as unset on a
  repository that has no commits yet.
- `nexus upgrade --dry-run` / `nexus rollback --dry-run` no longer block on
  the branch-mismatch confirmation prompt — a dry run is now guaranteed to be
  a non-interactive, side-effect-free preview, as documented.
- `nexus rollback`'s branch-mismatch confirmation no longer fires before the
  rollback target itself is validated, so a bad `--to-commit` sha or "nothing
  to roll back" fails immediately instead of asking the user to confirm a
  risky action first.

### Changed
- PyPI package renamed `nexus-platform` → `nexus-gitops`: `nexus-platform`
  turned out to already be taken by an unrelated project. The `nexus` command
  itself is unaffected — this only changes `pip install <name>`.

### Infrastructure
- `tests/integration/` — a Kind-based real-cluster suite (PRD §18): full
  `deploy`→`status`→`destroy` lifecycle, `deploy`/`destroy` idempotency, the
  documented git-sync soft-skip, preflight failures (missing kubectl,
  unreachable cluster), a partial-failure scenario (bad image →
  `ImagePullBackOff` → diagnosed by `status` → still fully recoverable via
  `destroy`), and a gated `chaos run` → recovery test. Deliberately excluded
  from the default `pytest` run (`tool.pytest.ini_options.testpaths` scoped to
  `tests/unit`) since it needs a live cluster and takes minutes, not seconds.
  All 10 tests live-verified against a real Kind cluster.
- `.github/workflows/ci.yml` — ruff + mypy + unit tests (with an 80% core
  coverage gate) on Python 3.10 and 3.13, plus two Kind e2e jobs (the main
  integration suite, and a separately gated/`continue-on-error` chaos job).
- `.github/workflows/release.yml` — builds and publishes to PyPI via Trusted
  Publishing (OIDC, no stored token) on a `v*` tag push; re-runs the full
  quality gate first as a safety net.
- `scripts/install.sh` — checks Python 3.10+, installs via `pipx` (preferred)
  or `pip --user`, verifies `nexus --version` after. Live-tested end-to-end
  against a locally built wheel (the real PyPI package doesn't exist until
  the first tagged release).
