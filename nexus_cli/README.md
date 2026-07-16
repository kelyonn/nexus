# nexus_cli — the Nexus Python package

This directory will hold the CLI implementation (Typer app). **No code yet** —
implementation follows the PRD's Phase 1 roadmap.

- **Spec:** the PRD §7 (commands), §11 (architecture), §16 (build order)
- **Skills needed:** the learning roadmap Stage 7 (Typer, subprocess, Jinja2)

## What lands here (Phase 1, in order)

1. `main.py` — Typer entry point (`nexus = "nexus_cli.main:app"` in pyproject.toml)
2. `core/` — config parsing/validation, preflight checks, kubectl/helm wrappers
3. `templates/` — Jinja2 manifests derived from `legacy/` (PRD §0 mapping)
4. `commands/` — `init`, `deploy`, `status`, `watch`, `destroy`, then Phase 2 commands
