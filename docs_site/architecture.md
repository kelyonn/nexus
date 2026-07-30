# Architecture

## The shape of it

```
nexus.yaml
    │  nexus_cli/core/config.py (Pydantic validation)
    ▼
Jinja2 templates (nexus_cli/templates/*.yaml.j2)
    │  nexus_cli/core/render.py
    ▼
Kubernetes manifests
    │  nexus_cli/core/kubectl.py / helm.py / argocd.py / git.py
    ▼
kubectl apply + git commit/push  →  ArgoCD Application  →  your cluster
```

`nexus deploy` never talks to the Kubernetes API directly for anything
complex — it shells out to `kubectl` and `helm` for one-shot operations, and
uses the `kubernetes` Python SDK only where streaming matters (`nexus
watch`, `nexus logs`). Every wrapper lives in `nexus_cli/core/` and is
unit-tested with the real subprocess calls mocked, plus exercised against a
real cluster in `tests/integration/` (Kind-based).

## Repository layout

```
nexus_cli/main.py        Typer app entry point, registers every command
nexus_cli/commands/      One module per command — option parsing, printing
nexus_cli/core/          The actual logic: config, detect, render, kubectl,
                         helm, argocd, git, chaos, logs, status, dashboard
nexus_cli/templates/     Jinja2 templates, derived from legacy/ manifests
dashboard/backend/       FastAPI API + static frontend server
dashboard/frontend/      Next.js control panel (builds to a static export)
examples/flask-demo/     Reference app, deployed by the e2e suite
tests/unit/              Unit tests, mocked subprocess/network
tests/integration/       Kind-based e2e: deploy/status/destroy, idempotency,
                         chaos, partial-failure
legacy/                  The original hand-written GitOps demo — read-only
```

Commands stay thin: `commands/deploy.py` parses `--config`/`--yes` and
prints progress, but every actual decision (what manifests to render,
whether ArgoCD is already installed, how to wait for sync) lives in
`core/`. This is what lets `tests/unit/` cover the logic without a cluster,
and what lets the dashboard backend reuse the exact same `core/` functions
the CLI uses — the CLI and the dashboard can never silently disagree about
what a given app's status means.

## Templates → manifests

Every Kubernetes manifest Nexus generates is a parameterized version of the
original hand-written demo in `legacy/` — `nexus-app` becomes
`{{ app.name }}`, a hardcoded image becomes `{{ app.image }}`, and so on.
Nothing is invented from scratch; see `nexus_cli/templates/README.md` for
the mapping.

| Template | Renders when |
|---|---|
| `namespace.yaml.j2` | always |
| `serviceaccount.yaml.j2` | always |
| `deployment.yaml.j2` | always |
| `service.yaml.j2` | always |
| `argocd-app.yaml.j2` | always |
| `pdb.yaml.j2` | `app.replicas >= 2` |
| `servicemonitor.yaml.j2` | `platform.monitoring` and `app.metricsPath` set |
| `prometheus-rules.yaml.j2` | `platform.monitoring` |
| `grafana-dashboard.yaml.j2` | `platform.monitoring` |
| `podchaos.yaml.j2` | `platform.chaos` |

`core/render.py`'s `template_names()` is the single place that decides which
of these apply to a given config — it's what both `nexus deploy` and
`nexus destroy` (for cleanup) consult.

## GitOps loop

`nexus deploy` doesn't apply manifests and stop there — it also commits them
to `<cwd>/k8s/` on `platform.branch` and pushes, then registers an ArgoCD
`Application` tracking that path. ArgoCD is what actually reconciles the
cluster against git afterward; Nexus's job ends at registration. This is why
`platform.branch` has to match your actual working branch — a mismatch
soft-skips the git-sync step (see
[Troubleshooting](troubleshooting.md#branch-mismatch-soft-skip)) rather than
aborting, so a misconfigured git setup doesn't break the "live in under ten
minutes" promise for local/demo use, but `sync` then has nothing to compare
against and stays `Unknown`.

`nexus upgrade`/`nexus rollback` follow the same loop: they only ever touch
`nexus.yaml`'s `app.image` field and commit/push that change — ArgoCD
detects the drift and rolls it out. Nexus never talks to the Deployment
directly for an upgrade; the git commit is the only mutation.

## The dashboard

`nexus dashboard` is one process: a FastAPI backend
(`dashboard/backend/main.py`) that serves two things on the same port
(3002) —

- `/api/*` — a thin read layer over the exact same `nexus_cli/core/*`
  functions the CLI uses (`dashboard/backend/routes.py`).
- everything else — the frontend's static export
  (`dashboard/frontend/out/`, produced by `next build` with `output:
  "export"`), served through a small `try_files`-style catch-all
  (`dashboard/backend/static.py`) rather than a full Next.js server.

That's what makes `pip install nexus-gitops[dashboard]` work without
Node.js on the end user's machine — Node is only needed to *build* a
release wheel (a hatchling build hook, `hatch_build.py`, runs `next build`
automatically when packaging), never to run one. Frontend development still
uses the normal `next dev` hot-reload workflow against a separately-running
backend; see `dashboard/frontend/README.md`.

The frontend itself is a small React SPA with three routes — Overview
(`/`), App Detail (`/apps?name=<app>` — a query param rather than a dynamic
segment, since a static export can't serve arbitrary dynamic routes without
knowing every app name at build time), and the GitOps Log (`/synclog`). No
charting library: CPU/memory sparklines are inline SVG, and the four
cluster-level Grafana panels (plus three more if `app.metricsPath` is set)
are embedded via iframe, with `nexus dashboard` auto-port-forwarding Grafana
and Prometheus so they work out of the box.

## Observability

`platform.monitoring: true` (the default) installs
[kube-prometheus-stack](https://github.com/prometheus-community/helm-charts/tree/main/charts/kube-prometheus-stack)
via Helm, and Nexus generates per-app `PrometheusRule`s and Grafana
dashboards alongside the Deployment. Cluster-level panels (pod availability,
restarts, CPU/memory, desired-vs-running) come from kube-state-metrics and
cAdvisor — no changes to your app required. App-level panels (request rate,
error rate, P95 latency) require your app to expose a Prometheus metrics
endpoint (`app.metricsPath`) — see the
[schema reference](schema.md#metricspath-metricsport).
