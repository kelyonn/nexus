# Nexus

> **Bring your app. Nexus handles the platform.**

Nexus is an open-source GitOps platform CLI. Point it at your app, and one
config file (`nexus.yaml`) plus one command (`nexus deploy`) gets you:

- **GitOps deployment** via [ArgoCD](https://argo-cd.readthedocs.io/)
- **Self-healing** — Kubernetes and ArgoCD both reconcile drift automatically
- **Observability** via [Prometheus](https://prometheus.io/) + [Grafana](https://grafana.com/)
- **Chaos testing** via [Chaos Mesh](https://chaos-mesh.org/) (optional)

All on your own cluster — no DevOps team required.

📖 **[Docs](https://kelyonn.github.io/nexus/)** · Apache-2.0 · Python 3.10+ ·
478 tests, 99% core coverage · not yet on PyPI — install from source below

## What it looks like

```
$ nexus deploy

  Nexus Deploy — nexus-app
  -------------------------------------------
  ✓ kubectl found (v1.36.2)
  ✓ helm found (v4.2.3)
  ✓ Cluster reachable -> minikube
  ✗ ArgoCD not installed → will install
  ✗ kube-prometheus-stack not installed → will install

  Deployment plan:
    1. Install ArgoCD → namespace: argocd
    2. Install kube-prometheus-stack → namespace: monitoring
    3. Apply app manifests → namespace: nexus-app
    4. Commit manifests to Git → k8s/
    5. Register ArgoCD app → tracking your repo @ main

  Proceed? [y/N]: y
  ...
  ✓ nexus-app is live
```

That's real, captured output — not a mockup. [Try it yourself](#try-it) below.

## Try it

Requires Python 3.10+, Docker, and [Minikube](https://minikube.sigs.k8s.io/)
(or [Kind](https://kind.sigs.k8s.io/)).

```bash
git clone https://github.com/kelyonn/nexus.git && cd nexus

python3 -m venv venv && source venv/bin/activate
pip install -e ".[dev]"

minikube start --driver=docker

cd examples/flask-demo
nexus deploy      # installs ArgoCD + monitoring, deploys the app — type y
nexus status        # replicas, pods, ArgoCD sync/health
nexus watch          # live pod events, Ctrl+C to stop
nexus logs            # tail every pod's logs, prefixed by pod name
nexus chaos run        # kill one pod, watch it recover
nexus doctor             # environment diagnostics — every problem, with a fix
nexus destroy              # type the app name to confirm
```

`nexus deploy` is idempotent — safe to run more than once. `nexus upgrade
--image <tag>` and `nexus rollback` also exist but need a real git remote
(see [INSTALLATION.md](INSTALLATION.md) to try those).

### The dashboard

```bash
pip install -e ".[dashboard]"   # fastapi/uvicorn — not in the base install
nexus dashboard                  # opens the browser, Ctrl+C to stop
```

A local control panel: an app grid, pod age and CPU/memory sparklines, a
chaos-trigger button, Grafana panels, and a GitOps sync log with real commit
messages. No Node/npm needed at install time — the frontend ships as a static
export baked into the package (a checkout needs one `npm run build` in
[dashboard/frontend](dashboard/frontend) first; see that directory's README).
Needs at least one app deployed to show anything.

## Documentation

Full docs, including the pieces above with more detail:
**<https://kelyonn.github.io/nexus/>**

| Page | What's in it |
|---|---|
| [Install & quickstart](https://kelyonn.github.io/nexus/install/) | A real app on Minikube or Kind in under ten minutes |
| [Command reference](https://kelyonn.github.io/nexus/commands/) | Every command and flag, straight from `--help` |
| [nexus.yaml schema](https://kelyonn.github.io/nexus/schema/) | Every field, its type, default, and validation rule |
| [Architecture](https://kelyonn.github.io/nexus/architecture/) | How the CLI, manifests, ArgoCD, and dashboard fit together |
| [Multiple environments](https://kelyonn.github.io/nexus/multi-environment/) | Staging and prod from separate `nexus.yaml` files |
| [Troubleshooting](https://kelyonn.github.io/nexus/troubleshooting/) | Real problems hit during development, and their fixes |
| [Cloud quick-starts](https://kelyonn.github.io/nexus/cloud/) | EKS/GKE/AKS notes (⚠️ not yet verified against real cloud clusters) |

Built from [docs_site/](docs_site) with MkDocs Material, deployed to GitHub
Pages on every push to `main` that touches the site. To work on it locally:

```bash
pip install -e ".[docs]"
mkdocs serve                     # http://127.0.0.1:8000
mkdocs build --strict && python scripts/check_links.py
```

## Repository map

```
nexus_cli/          The Python package (Typer CLI) — the full command suite
dashboard/backend/  FastAPI API + static frontend server for the dashboard (127.0.0.1:3002)
dashboard/frontend/ Next.js control panel, built to a static export (dashboard/frontend/out/)
examples/           Sample apps for demos and e2e tests (flask-demo, live-tested)
tests/              478 unit tests (99% core coverage) + a Kind-based integration suite
docs_site/          Source for the published site (MkDocs Material → GitHub Pages)
overrides/          home.html — the landing page at kelyonn.github.io/nexus
legacy/             The original hand-written GitOps demo (archived, read-only)
```

## The story

This started as a hand-built GitOps demo — a Flask app wired by hand to
Kubernetes, ArgoCD, Prometheus, and Chaos Mesh (see
[legacy/](legacy/README.md)). That setup took days, and almost none of it was
specific to the app. Nexus is the tool that generates all of it from one
config file.

## Contributing

PRs welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) for setup, the pre-PR
gate, and this project's scope boundaries. Fresh-install notes:
[INSTALLATION.md](INSTALLATION.md). Bigger ideas that are real but
deliberately not started yet are tracked in
[FUTURE-SCOPE.md](FUTURE-SCOPE.md), with the design questions each one needs
answered first.

## License

Apache-2.0.
