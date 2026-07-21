# Nexus

> **Bring your app. Nexus handles the platform.**

Nexus is an open-source GitOps platform CLI that gives any developer
production-grade Kubernetes infrastructure in minutes. Run `nexus init` in your
project, fill in one YAML file, run `nexus deploy` — and get GitOps deployment
(ArgoCD), self-healing, observability (Prometheus + Grafana), and optional
chaos testing (Chaos Mesh) on **your own cluster**, without a DevOps team.

## Status

✅ **Phase 1 (core CLI) is done.** `nexus init`, `deploy`, `status`, `watch`,
and `destroy` all exist and are verified against a real Minikube cluster —
installing ArgoCD, deploying an app, checking its health, streaming its pod
events, and tearing it down again, twice each way to confirm idempotency.

Not yet built: `chaos`, `logs`, `upgrade`, `rollback`, `doctor` (Phase 2), and
the dashboard (Phase 3). Not yet published to PyPI/Homebrew — install from
source for now (see [Try it](#try-it) below).

The original manifest-based demo that inspired the CLI still lives — runnable —
in [legacy/](legacy/README.md).

## The target experience

```
$ nexus init
  Detected stack: Node.js (package.json found)
  ✓ Created nexus.yaml

$ nexus deploy
  ✓ kubectl found          ✓ helm found          ✓ Cluster reachable
  Deployment plan:
    1. Install ArgoCD            → namespace: argocd
    2. Install kube-prom-stack   → namespace: monitoring
    3. Apply app manifests       → namespace: my-app
    4. Register ArgoCD app       → tracking your repo @ main
  Proceed? [y/N]: y
  ...
  ✓ my-app is live — Synced + Healthy
```

One config file (`nexus.yaml`), one command, and your app is deployed with
GitOps, self-healing, metrics dashboards, and health probes — the setup that
normally takes days of YAML wrangling.

## Repository map

```
nexus_cli/     The Python package (Typer CLI) — Phase 1, in progress
examples/      Sample apps for demos and e2e tests
tests/         Unit + integration tests
legacy/        The original hand-written GitOps demo (archived, read-only)
```

## The story

This project started as a hand-built GitOps demo: a Flask app, Kubernetes
manifests, ArgoCD, Prometheus rules, and Chaos Mesh experiments, all wired by
hand (see [legacy/](legacy/README.md)). Building it revealed the problem worth
solving: **that setup took days, and almost none of it was specific to the
app.** Nexus is the tool that generates all of it from one config file — the
demo is exactly the output `nexus deploy` will produce automatically.

## Contributing

PRs welcome once Phase 1 scaffolding lands. Please include what changed, why,
and how you tested it. Development setup: [INSTALLATION.md](INSTALLATION.md).

## License

Apache-2.0.
