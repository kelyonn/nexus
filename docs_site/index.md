---
template: home.html
title: Nexus — Bring your app. Nexus handles the platform.
description: >-
  Nexus is an open-source GitOps platform CLI. One nexus.yaml, one command, and
  your app runs on Kubernetes with ArgoCD GitOps, self-healing, Prometheus and
  Grafana observability, and optional Chaos Mesh testing — on your own cluster.
hide:
  - navigation
  - toc
---

<!--
  This page is rendered entirely by overrides/home.html (see the `template:`
  key above) — the terminal-styled splash landing page. The body below is not
  rendered; it exists so the page has content for search indexing and so the
  links stay covered by `mkdocs build --strict`'s internal-link check.

  To edit what visitors actually see on the homepage, edit overrides/home.html.
-->

Nexus is an open-source GitOps platform CLI that gives any developer
production-grade Kubernetes infrastructure in minutes. Run `nexus init` in
your project, fill in one YAML file, run `nexus deploy` — and get GitOps
deployment (ArgoCD), self-healing, observability (Prometheus + Grafana), and
optional chaos testing (Chaos Mesh) on your own cluster, without a DevOps
team.

- [Install & quickstart](install.md) — get a real app deployed to Minikube or
  Kind in under ten minutes.
- [Command reference](commands.md) — every command, every flag, straight from
  `--help`.
- [nexus.yaml schema](schema.md) — every field, its type, default, and
  validation rule.
- [Architecture](architecture.md) — how the CLI, the generated manifests,
  ArgoCD, and the local dashboard fit together.
- [Multiple environments](multi-environment.md) — running staging and prod
  from separate `nexus.yaml` files.
- [Troubleshooting](troubleshooting.md) — real problems hit during
  development, and their fixes.
- [Cloud quick-starts](cloud/index.md) — EKS/GKE/AKS notes.
