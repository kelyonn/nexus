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
- `nexus dashboard` — a local browser control panel. `dashboard/backend`
  (FastAPI, `127.0.0.1:3002`) exposes `GET /api/apps` (via
  `argocd.list_managed_apps()`, discovering every Nexus-managed app by its
  `managed-by: nexus` label — the CLI operates on one app at a time, but the
  dashboard shows all of them), `GET /apps/{name}/pods`,
  `GET /apps/{name}/synclog`, and the one mutating endpoint,
  `POST /apps/{name}/chaos`, gated behind a per-session bearer token
  `nexus dashboard` generates fresh at launch (PRD §13 — local CSRF
  protection, since a page in the browser can POST to 127.0.0.1:3002
  directly regardless of CORS). `dashboard/frontend` (Next.js, port 3001)
  renders an Overview grid, an App Detail view (pod list, a chaos-trigger
  button with a live recovery indicator, and an embedded Grafana panel —
  Grafana isn't exposed outside the cluster automatically, so this
  documents the manual `kubectl port-forward` step rather than pretending
  it's automatic), and a GitOps Log. `nexus dashboard` launches both,
  waits for the backend's health check, and opens the browser; Ctrl+C
  tears both down (`core/dashboard.py`).
- `deploy.py` now sets Grafana's `allow_embedding`/`cookie_samesite` Helm
  values so the dashboard's iframe panels aren't silently blocked by
  Grafana's default `X-Frame-Options: DENY` (PRD §15's mitigation, not
  previously implemented).
- Dashboard: pod age (App Detail, from `creationTimestamp`), CPU/memory
  sparklines fed by a new `GET /apps/{name}/metrics` endpoint that proxies
  Prometheus `query_range` (`core/dashboard.py` gained a generic
  `start_port_forward()`, reused for both Grafana and Prometheus), and real
  commit subjects in the GitOps Log (`git.commit_subject()`) instead of a
  bare SHA (PRD §10.2/§10.3).
- App-level HTTP metrics (PRD §10.4): optional `app.metricsPath`/
  `metricsPort` in `nexus.yaml` render a `ServiceMonitor` so
  kube-prometheus-stack scrapes the app directly, plus three new Grafana
  dashboards (request rate, error rate, P95 latency). `examples/flask-demo`
  is instrumented with `prometheus-flask-exporter` as the reference
  implementation (its checked-in `nexus.yaml` doesn't set `metricsPath`
  itself, since the pre-built Docker Hub image it deploys predates the
  instrumentation — see the comment there). The dashboard shows these panels
  only when the backend confirms a `ServiceMonitor` actually exists for that
  app.
- `nexus dashboard` no longer needs Node/npm on the machine running it:
  `dashboard/frontend` now builds to a static export (`next build` with
  `output: "export"`), and the FastAPI backend serves it directly alongside
  its own `/api/*` routes — one process instead of two. A hatchling build
  hook (`hatch_build.py`) builds the frontend into the wheel automatically;
  Node is now a maintainer-time requirement for building a release, not a
  user-time one for running `pip install`. `/apps/[name]` became `/apps?name=`
  (a static export can't serve arbitrary dynamic segments) with no change to
  what the page shows.

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
- `deploy`/`upgrade`/`rollback` no longer time out and report failure on a
  fully successful rollout: on the ArgoCD version currently installed,
  `health` can stay `Progressing` indefinitely even once Kubernetes reports
  the Deployment fully available. `argocd.wait_for_healthy()` now
  cross-checks ground truth via replica counts when `sync == Synced` and
  `health == Progressing`, and the three commands print an honest note when
  this override fired. Chart versions (`argo`/`prometheus`/`chaos`) are also
  now pinned in `deploy.py` per PRD §15's stated mitigation.
- `imagePullPolicy: Always` was hardcoded, which made `status.image_pull_fix()`'s
  own documented Minikube fix (`minikube image load` + redeploy) impossible —
  the kubelet would just try the registry again and fail the same way. Added
  `app.imagePullPolicy` (`Always | IfNotPresent | Never`, default `Always`) to
  `nexus.yaml`, templated it, and updated the fix message to mention setting
  `IfNotPresent` alongside the load command.

### Changed
- PyPI package renamed `nexus-platform` → `nexus-gitops`: `nexus-platform`
  turned out to already be taken by an unrelated project. The `nexus` command
  itself is unaffected — this only changes `pip install <name>`.
- New optional `dashboard` extra (`pip install "nexus-gitops[dashboard]"`) for
  `fastapi`/`uvicorn` — kept out of the base install so the core CLI stays
  light for users who never touch the dashboard.
- Pulled several data-gathering functions out of their Typer commands into
  `core/`, so the dashboard backend reads cluster state through the exact
  same code the CLI does rather than a second implementation:
  `core/chaos.py` (experiment building/apply, the webhook retry),
  `core/logs.py` (pod log fetch), and `core/status.py` (pod/replica data).
  Each command module is now a thin wrapper over its `core/` counterpart;
  no behavior changed.

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
  A `dashboard-frontend` job now lints, type-checks, and production-builds
  the Next.js app; `lint-and-unit` installs the `dashboard` extra so the
  dashboard's own unit tests (mocked FastAPI `TestClient`, mocked
  subprocess/network) run in CI instead of skipping.
- `.github/workflows/release.yml` — builds and publishes to PyPI via Trusted
  Publishing (OIDC, no stored token) on a `v*` tag push; re-runs the full
  quality gate first as a safety net.
- `scripts/install.sh` — checks Python 3.10+, installs via `pipx` (preferred)
  or `pip --user`, verifies `nexus --version` after. Live-tested end-to-end
  against a locally built wheel (the real PyPI package doesn't exist until
  the first tagged release).
