# Changelog

All notable changes to Nexus are documented here. Format based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this project follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-08-10

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
- Docs site (`docs_site/`, MkDocs Material, deployed to GitHub Pages via
  `.github/workflows/docs.yml`): install/quickstart, a command reference
  generated from real `--help` output, the full `nexus.yaml` schema, an
  architecture overview, and a troubleshooting page seeded from real bugs
  hit during development (ImagePullBackOff on Minikube, the ArgoCD health
  quirk, the branch-mismatch soft-skip, the Chaos Mesh webhook race) rather
  than a hypothetical FAQ. Cloud quick-starts for EKS/GKE/AKS are included
  but explicitly labeled untested — everything else on the site has been
  live-verified against Minikube/Kind. `docs_site/` is the site's source;
  this repo's own `docs/` remains a separate, gitignored, local-only
  directory and is not published. `CONTRIBUTING.md`, issue templates
  (bug report / feature request), and a PR template were also added.
- `docs_site/multi-environment.md` documents running staging/prod from
  separate `nexus.yaml` files via `--config` — what already worked, just
  undocumented, plus the two fields (`platform.branch`, `app.name`) that
  actually keep two environments from colliding. `FUTURE-SCOPE.md` tracks
  bigger deferred ideas (secret management, a real `environments:` schema,
  dashboard log streaming) with the design questions each needs answered
  first, following an external review of the project.
- Dashboard frontend types (`dashboard/frontend/lib/api.generated.ts`) are
  now generated from the backend's Pydantic response models
  (`scripts/generate_dashboard_types.py`, via Pydantic's
  `models_json_schema` + `json-schema-to-typescript`) instead of hand-kept
  in sync — a real, repeated source of bugs while building the dashboard
  (`has_http_metrics`, `created_at`, and `subject` each needed adding by
  hand to both sides). CI regenerates and fails if the committed output is
  stale (`.github/workflows/ci.yml`'s `dashboard-frontend` job).
- `app.registry` in `nexus.yaml`: closes the most common `ImagePullBackOff`
  cause — a private registry (ECR, GCR, a private GHCR/Docker Hub repo)
  Kubernetes has no credentials for. Takes environment variable *names*
  (`usernameEnv`/`passwordEnv`), never raw credentials — `nexus.yaml` gets
  committed to git, so a real credential there would recreate the exact
  problem GitOps exists to avoid. `nexus deploy` reads the actual
  credentials from those env vars at deploy time and imperatively
  creates/updates a `kubernetes.io/dockerconfigjson` Secret via `kubectl`
  (never rendered into the committed `k8s/` directory), written through a
  short-lived 0600 temp file rather than a `--docker-password=...` CLI
  argument (avoids leaking it via `ps aux` for the life of the process).
  `deployment.yaml.j2` references it via `imagePullSecrets` when set.
  `nexus doctor` checks credential env vars are present (never prints their
  values). Live-verified against the real cluster: missing credentials
  abort `nexus deploy` clearly (and are caught proactively by `nexus
  doctor`), the created Secret's decoded content is exactly correct,
  the Deployment correctly references it, rotating credentials and
  redeploying updates the Secret in place (idempotent, no duplication), and
  `nexus destroy` cleans it up (implicitly, via namespace deletion).
- `nexus destroy --dry-run`: prints exactly the same resource list the real
  run already showed before its confirmation prompt (now also including
  the imagePullSecret when `app.registry` is set — a gap in that listing
  found while touching it), then stops before prompting. A second, cheaper
  safety net on top of the existing typed-name confirmation for the most
  destructive command in the CLI.
- `app.secrets` in `nexus.yaml`: real app secrets (a DB password, an API
  key), modeled directly on `app.registry`'s existing pattern — each entry
  names an environment variable to read the actual value from at deploy
  time, never the value itself. `nexus deploy` creates/updates the resulting
  Secret imperatively via `kubectl` (short-lived 0600 temp files, one per
  key, never a `--from-literal=...` argument) and never writes it to `k8s/`.
  The Deployment references it via `valueFrom.secretKeyRef`. Applied and
  removed alongside the app's namespace, same as the registry Secret.
  `nexus doctor` checks the named env vars are set (never prints their
  values). `app.env` additionally now rejects values that look
  credential-shaped (a deny-list on the field name plus a couple of
  value patterns) with a `plaintext: true` escape hatch for false positives
  — nudging real secrets toward `app.secrets` instead of `nexus.yaml`'s
  free-text `env` list, which gets committed to git. See
  `docs_site/schema.md`'s `secrets` section and `FUTURE-SCOPE.md` §1 for
  what's still open (encrypting a secret at rest in git itself).
- `nexus logs --follow` / `-f`: streams every matching pod's logs live,
  concurrently, prefixed by pod name like the existing snapshot output —
  the same `kubectl logs -f` mental model `nexus watch` already uses for
  pod events. One thread per pod (`kubernetes.watch.Watch()` genuinely
  supports following a log stream, not just watching list events — verified
  against the installed SDK's source, not assumed). Live-verified against a
  real cluster, including Ctrl+C actually stopping it: an initial test via a
  backgrounded shell job falsely suggested a hang, which turned out to be
  the shell itself ignoring `SIGINT` for background jobs, not this code —
  re-tested with a wrapper that resets `SIGINT` to its default disposition
  first, matching a real terminal, and it stops immediately as intended.
- Pod hardening on the generated Deployment: a dedicated per-app
  `ServiceAccount` (`serviceaccount.yaml.j2`) with `automountServiceAccountToken:
  false` rather than falling back to the namespace's `default` one;
  `allowPrivilegeEscalation: false` and dropping all Linux capabilities on
  every container (no ordinary app needs either, so these are unconditional,
  not configurable); a `startupProbe` so a slow-booting container gets up to
  150s before readiness/liveness start counting against it; and
  `topologySpreadConstraints` (`ScheduleAnyway`, so it helps across multiple
  nodes without stranding a replica `Pending` forever on the single-node
  Kind/Minikube clusters this project targets). A new opt-in `app.security`
  block (`runAsNonRoot`, `runAsUser`, `readOnlyRootFilesystem`) covers the
  hardening that depends on the image itself and so can't be forced by
  default — `nexus init` sets `runAsNonRoot: true` for every newly generated
  `nexus.yaml`. Apps with `replicas >= 2` also get a `PodDisruptionBudget`
  (`maxUnavailable: 1`), omitted at `replicas: 1` where it would block every
  voluntary disruption instead of protecting anything. See
  `docs_site/schema.md`'s `security` section.
- `nexus deploy`'s "Access your app" message now also suggests `minikube
  service <name> -n <name>` when the current context is Minikube — it tunnels
  a `ClusterIP` Service and opens the browser automatically, one command
  instead of a manual `port-forward` plus opening the URL yourself. The
  `kubectl port-forward` instructions are still shown alongside it, since
  they're the only option that works on every cluster.
- `nexus dashboard` now prints the Grafana admin login (`grafana_admin_credentials()`
  in `core/dashboard.py`, decoding kube-prometheus-stack's generated
  `admin-user`/`admin-password` Secret) right when it forwards Grafana, so the
  one place you're actually going to hit that login screen — the dashboard's
  embedded panels — also tells you the credentials, instead of leaving you to
  go hunt for them separately.
- `nexus open` — port-forwards the app's Service and opens it in your browser,
  until Ctrl+C. `nexus deploy` deliberately never does this itself: it's a
  one-shot, idempotent command, and a background tunnel left running after it
  exits would collide with a later re-deploy on the same local port with no
  lifecycle anyone's tracking. This is the dedicated, explicit way to view a
  deployed app instead — same shape as `nexus watch`. The README's "Try it"
  quickstart previously ran through `deploy`/`status`/`watch`/`logs`/`chaos
  run`/`doctor`/`destroy` without ever mentioning how to actually look at the
  running app; it now includes this step.

### Fixed
- `deploy`/`upgrade`/`rollback` could report a rollout as successful while it
  was actually stuck: the ground-truth cross-check against ArgoCD's own
  health (added for the `Progressing`-stuck-forever quirk below) compared
  only `availableReplicas` against the desired count, which a stale
  ReplicaSet's still-healthy old pods can satisfy on their own during a
  rollout to a broken image — and separately, ArgoCD's own `health` field
  could itself briefly report `Healthy` right as a bad rollout started,
  before it noticed the new ReplicaSet was failing, bypassing the
  cross-check entirely since it only guarded the `Progressing` case. Found by
  live-deploying a broken image end-to-end ahead of the first release.
  `status.rollout_complete()` now also requires `updatedReplicas` to meet the
  desired count, and `wait_for_healthy()` cross-checks ground truth for both
  `Healthy` and `Progressing` before trusting either.
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
- `nexus deploy` now applies the Namespace and both kinds of Secret
  (imagePullSecret, and the new `app.secrets` Secret) before the Deployment
  that references them, instead of after — the previous ordering meant a
  fresh `nexus deploy` briefly applied a Deployment referencing a Secret
  that didn't exist yet (self-correcting once kubelet retried, but a real
  race, and now closed for both Secret kinds together).
- Values interpolated into generated manifests (`app.env[].value`,
  `app.env[].name`, `platform.branch`, `app.healthPath`, `app.metricsPath`)
  are now schema-validated to a safe charset and/or JSON-escaped (`| tojson`)
  at the template layer, and every rendered manifest is parsed before being
  returned. Previously an env value containing a bare double quote produced
  invalid YAML — a real bug, not just a hardening concern, since it's a
  completely ordinary value to want to set. `core/render.py` also gained a
  parse-and-verify step so malformed template output now fails as a clear
  `NexusError` instead of a raw parser error reaching `kubectl apply`.

### Changed
- Docs updated for `nexus open` and the Grafana-credentials change:
  `docs_site/commands.md` gained an entry for `nexus open`, and both it and
  `docs_site/install.md` mention the Minikube `deploy` shortcut and the
  Grafana login `nexus dashboard` now prints; `docs_site/exposing-your-app.md`
  leads with `nexus open` instead of the raw `kubectl port-forward` command.
  `README.md` trimmed: dropped "The story" and "Repository map" (narrative
  and contributor-orientation content that doesn't help someone evaluating or
  using the tool), the docs-build snippet under "Documentation" now points at
  `CONTRIBUTING.md` instead of duplicating it, and the stale `478 tests`
  count is corrected to `597`.
- The CLI's terminal output now draws from one shared palette instead of each
  command formatting itself. `core/output.py` gained `header()` (the
  `Nexus X — name` banner over its rule), `check()` (colored ✓/✗ checklist
  lines), `info()` (blue, for work in progress — `[i/n]` step announcements,
  `Waiting for sync...`, `Watching pods...`), and `banner()` (the NEXUS
  wordmark, shown by `nexus init` only — it's the first command a new user
  runs, and repeating it on frequent commands would just be noise).
  `success()`/`warn()`/`print_error()` moved to the same muted
  blue/green/amber/red set. No output text changed, so `CliRunner`-based
  tests (which strip color) were unaffected.
- Multi-step commands are spaced out rather than run together: every step in
  `deploy` and `destroy` trails a blank line whether it succeeded or was
  skipped, and `print_error()` emits its own leading blank line — which fixes
  the spacing at all ~35 call sites at once instead of relying on each caller
  to remember.
- The docs site homepage is now a terminal-styled landing page
  (`overrides/home.html`, selected by `docs_site/index.md`'s `template:`
  front matter) rather than a plain markdown page. Every other page keeps
  Material's stock chrome, and every existing docs URL is unchanged.
  `scripts/check_links.py` was added because `mkdocs build --strict` only
  validates links written in markdown — it walks the *built* HTML so the
  template's links are covered too, and runs in the docs workflow.
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
- `.github/workflows/ci.yml` — ruff + mypy + unit tests on Python 3.10 and
  3.13, plus two Kind e2e jobs (the main integration suite, and a separately
  gated/`continue-on-error` chaos job). A `dashboard-frontend` job now lints,
  type-checks, and production-builds the Next.js app; `lint-and-unit`
  installs the `dashboard` extra so the dashboard's own unit tests (mocked
  FastAPI `TestClient`, mocked subprocess/network) run in CI instead of
  skipping. The coverage gate now covers all of `nexus_cli` (not just
  `nexus_cli/core`) at a measured 90% floor — `nexus_cli/commands/` (the
  interactive confirmation logic in `deploy`/`destroy` included) was
  previously outside the gate entirely despite having its own tests. Both
  this job's quality checks and `release.yml`'s now run through the same
  `scripts/gate.sh`.
- `.github/workflows/release.yml` — builds and publishes to PyPI via Trusted
  Publishing (OIDC, no stored token) on a `v*` tag push; re-runs the full
  quality gate first as a safety net. Now also: verifies the pushed tag
  matches `nexus_cli.__version__` (and that `CHANGELOG.md` has a section for
  it) before doing anything else; installs the `dashboard` extra so the
  dashboard backend's own tests actually run on this path instead of
  skipping; builds the sdist and wheel as independent, explicit artifacts;
  asserts the dashboard frontend and the manifest templates both landed in
  the built wheel (same check `ci.yml`'s `wheel-build` job already makes on
  every PR, now also on the one build that's actually published); and
  finishes with an install-from-wheel smoke test in a throwaway venv
  (`nexus --version`, `nexus init`, a config that loads, the dashboard
  package importing) before publishing. `scripts/gate.sh` centralizes the
  ruff/mypy/pytest+coverage gate that CI, this workflow, and `CONTRIBUTING.md`
  all now run identically — previously the release path installed fewer
  extras and skipped the coverage floor entirely, so it was possible for a
  release to publish something CI itself would have rejected.
- `pyproject.toml`'s sdist target is now scoped explicitly
  (`[tool.hatch.build.targets.sdist]`) instead of hatchling's default of
  "every git-tracked file," which would have shipped `legacy/`, `tests/`,
  `docs_site/`, and `.github/` inside a source distribution meant to build
  one Python package. Verified by building the sdist, extracting it in
  isolation, and building the wheel from that extraction — confirming the
  scoped file list is actually sufficient (this is also what `pip install`
  from a source distribution, or `python -m build`'s default wheel-from-sdist
  path, does under the hood).
- `hatch_build.py`'s frontend-build hook now skips entirely on an editable
  install (`pip install -e .` never needed it — only `nexus_cli` is
  live-linked by an editable install) instead of running a full `npm ci` +
  build unconditionally, and a failing `npm` command now degrades to the
  same "built without the dashboard, here's the fix" warning as `npm` being
  absent, instead of aborting the whole `pip install` — matching what this
  hook's own docstring already said it did.
- `scripts/install.sh` — checks Python 3.10+, installs via `pipx` (preferred)
  or `pip --user`, verifies `nexus --version` after. Live-tested end-to-end
  against a locally built wheel (the real PyPI package doesn't exist until
  the first tagged release).
- `tests/integration/conftest.py`'s tolerance for a non-zero `nexus deploy`
  exit (needed because every test's `scratch_repo` has no git remote, so
  ArgoCD's `sync` can never reach `Synced`) now parses the CLI's own
  reported `sync`/`health` status instead of matching on the error message's
  substring alone. Previously *any* cause of the "did not become Synced +
  Healthy" timeout was tolerated — including a genuinely `Degraded` app,
  which would have passed the suite silently. Now only `sync` never reaching
  `Synced` is tolerated; a `Synced`-but-unhealthy result fails the test.
  Covered by a new fast unit test (`tests/unit/test_integration_conftest.py`)
  so this parsing logic doesn't need a live cluster to verify.
- `ci.yml`'s `push` trigger is now scoped to `main` — previously unscoped,
  so every commit to a branch with an open PR ran the full suite (two Kind
  clusters, four npm builds) twice: once via `push`, once via `pull_request`.
- Added `chaos-canary.yml`, a weekly scheduled (and manually triggerable) run
  of the chaos integration test *without* `continue-on-error`. The PR-facing
  `integration-chaos` job stays soft-gated on purpose (Chaos Mesh's Helm
  install settling on Kind's shared CI runners is infra-timing that must
  never block a merge), which also means a persistent real regression there
  would fail silently forever with no other signal — this gives it one.
- `app.serviceType` (`ClusterIP` \| `NodePort` \| `LoadBalancer`, default
  `ClusterIP`) — the generated Service defaulted to `LoadBalancer` (the
  legacy demo's value), which sits `<pending>` forever on a bare Kind/
  Minikube cluster and provisions a real, billed load balancer per app on a
  real cloud one, despite `nexus deploy`'s own success message always
  pointing users at `kubectl port-forward` — which works against any Service
  type. `LoadBalancer`/`NodePort` are still available, just no longer the
  default. Live-verified: applied the regenerated Service to a running app
  and confirmed `port-forward` still reaches it (HTTP 200) under `ClusterIP`.
- New docs page, [Exposing your app](https://kelyonn.github.io/nexus/exposing-your-app/):
  the three actual options for reaching a deployed app (port-forward,
  `serviceType`, bring-your-own Ingress + cert-manager with a worked
  example) and why there's no Ingress template — a documented interop
  boundary instead of an unexplained gap.
- The three app-level Grafana panels tied to `prometheus-flask-exporter`'s
  metric names (request rate, error rate, P95 latency) are now also gated on
  `app.stack == "flask"`, not just `app.metricsPath` being set — a
  `node`/`generic` app with `metricsPath` configured still gets scraped (the
  ServiceMonitor is stack-agnostic) but no longer gets three permanently
  empty panels querying metric names its own exporter never emits.
- `FUTURE-SCOPE.md` gained two new entries: HPA support (blocked on a real
  design decision about how it should coexist with ArgoCD's `selfHeal`
  reverting `spec.replicas` — not just "not built yet"), and a per-app
  `app.namespace` override (deliberately not planned — the current
  one-app-one-namespace invariant is what makes `nexus destroy`'s
  whole-namespace deletion safe).
- `starlette>=1.0` added alongside `httpx2` in the `dev` extra — `httpx2` is
  real, not a typo (already documented in `FUTURE-SCOPE.md`), but the floor
  that makes it actually get used by FastAPI's `TestClient` was previously
  undeclared.
