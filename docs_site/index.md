# Nexus

**Bring your app. Nexus handles the platform.**

Nexus is an open-source GitOps platform CLI that gives any developer
production-grade Kubernetes infrastructure in minutes. Run `nexus init` in
your project, fill in one YAML file, run `nexus deploy` — and get GitOps
deployment ([ArgoCD](https://argo-cd.readthedocs.io/)), self-healing,
observability ([Prometheus](https://prometheus.io/) +
[Grafana](https://grafana.com/)), and optional chaos testing
([Chaos Mesh](https://chaos-mesh.org/)) on **your own cluster**, without a
DevOps team.

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
normally takes days of YAML wrangling. That output above is real, captured
output, not a mockup.

## Where to go next

- **[Install & quickstart](install.md)** — get a real app deployed to
  Minikube or Kind in under ten minutes.
- **[Command reference](commands.md)** — every command, every flag, straight
  from `--help`.
- **[nexus.yaml schema](schema.md)** — every field, its type, default, and
  validation rule.
- **[Architecture](architecture.md)** — how the CLI, the generated manifests,
  ArgoCD, and the local dashboard fit together.
- **[Troubleshooting](troubleshooting.md)** — real problems hit during
  development, and their fixes.
- **[Cloud quick-starts](cloud/index.md)** — EKS/GKE/AKS notes (⚠️ untested
  against real cloud clusters — everything else on this site is
  Minikube/Kind-verified).

## What's built

All eleven commands — `init`, `deploy`, `status`, `watch`, `destroy`,
`logs`, `chaos run` / `chaos schedule`, `doctor`, `upgrade`, `rollback`, and
`dashboard` — exist and are live-verified against real clusters, not just
unit-tested. The local dashboard (`nexus dashboard`) ships as a static export
baked into the package, so `pip install nexus-gitops[dashboard]` works with
no Node.js on your machine.

Not yet published to PyPI — see the [repo README](https://github.com/kelyonn/nexus#readme)
for installing from source.
