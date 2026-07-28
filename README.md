# Nexus

> **Bring your app. Nexus handles the platform.**

Nexus is an open-source GitOps platform CLI that gives any developer
production-grade Kubernetes infrastructure in minutes. Run `nexus init` in your
project, fill in one YAML file, run `nexus deploy` — and get GitOps deployment
(ArgoCD), self-healing, observability (Prometheus + Grafana), and optional
chaos testing (Chaos Mesh) on **your own cluster**, without a DevOps team.

## Status

✅ **Phase 1 + Phase 2 (the full CLI) are done.** All ten commands —
`init`, `deploy`, `status`, `watch`, `destroy`, `logs`, `chaos run`/`chaos
schedule`, `doctor`, `upgrade`, and `rollback` — exist and are verified
against real clusters (Minikube and Kind): deploying an app, streaming logs
and pod events, killing a pod and watching it recover, diagnosing a broken
environment, bumping an image through GitOps, and rolling it back through
`git revert` — proven to survive ArgoCD's self-heal, not just claimed to.

Not yet published to PyPI/Homebrew — install from source for now (see
[Try it](#try-it) below). The dashboard (Phase 3) hasn't been built yet.

The original manifest-based demo that inspired the CLI still lives — runnable —
in [legacy/](legacy/README.md).

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

One config file (`nexus.yaml`), one command, and your app is deployed with
GitOps, self-healing, metrics dashboards, and health probes — the setup that
normally takes days of YAML wrangling. This is real, captured output, not a
mockup — see [Try it](#try-it) to run it yourself.

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

`nexus deploy` is safe to run more than once — it skips components that are
already installed and never duplicates resources. `nexus upgrade --image
<tag>` and `nexus rollback` also exist but need a real git remote to push to
(see [INSTALLATION.md](INSTALLATION.md) if you want to try those).

## Repository map

```
nexus_cli/     The Python package (Typer CLI) — the full command suite
examples/      Sample apps for demos and e2e tests (flask-demo, live-tested)
tests/         268 unit tests (98% core coverage) + a Kind-based integration suite
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

PRs welcome. Please include what changed, why,
and how you tested it. Development setup: [INSTALLATION.md](INSTALLATION.md).

## License

Apache-2.0.
