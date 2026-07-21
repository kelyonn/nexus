# core/ — shared logic under the commands

Modules (PRD §11):

- `config.py` — load/validate `nexus.yaml` (schema + rules: PRD §9), apply
  defaults — Pydantic v2 models
- `detect.py` — stack detection for `nexus init` (PRD §7.1: package.json →
  Node, app.py+requirements.txt → Flask)
- `output.py` — the `NexusError` what/why/fix shape (PRD §12) and terminal
  output helpers
- `render.py` — Jinja2 rendering of `templates/` from validated config
- `preflight.py` — kubectl/helm/cluster/config checks (PRD §7.2)
- `kubectl.py`, `helm.py`, `git.py` — subprocess wrappers with parsed output,
  timeouts, and what/why/fix error translation
- `argocd.py` — Application registration, sync status polling, explicit sync
  trigger

This is the 80%-coverage target zone (PRD §18) — currently at 99%.
