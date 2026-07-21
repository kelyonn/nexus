# nexus_cli — the Nexus Python package

The CLI implementation (Typer app). Phase 1 (Week 1) is done.

- **Spec:** the PRD §7 (commands), §11 (architecture), §16 (build order)
- **Skills needed:** the learning roadmap Stage 7 (Typer, subprocess, Jinja2)

## What's here

1. `main.py` — Typer entry point, all five Phase 1 commands registered
2. `core/` — config parsing/validation, preflight checks, and the
   kubectl/helm/git/argocd subprocess wrappers
3. `templates/` — all 7 Jinja2 manifests derived from `legacy/` (PRD §0 mapping)
4. `commands/` — `init`, `deploy`, `status`, `watch`, `destroy` — built and
   verified against a real Minikube cluster, not just unit-tested

## Still to come (Week 2, Phase 2)

`chaos`, `logs`, `upgrade`, `rollback`, `doctor`
