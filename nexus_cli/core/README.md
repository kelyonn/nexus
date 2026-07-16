# core/ — shared logic under the commands

Planned modules (PRD §11):

- `config.py` — load/validate `nexus.yaml` (schema + rules: PRD §9), apply defaults
- `detect.py` — stack detection for `nexus init` (PRD §7.1: package.json → Node, app.py+requirements.txt → Flask)
- `preflight.py` — kubectl/helm/cluster/config checks (PRD §7.2)
- `kubectl.py`, `helm.py` — subprocess wrappers with parsed output
- `argocd.py` — Application registration, sync status polling, explicit sync trigger
- `render.py` — Jinja2 rendering of `templates/` from validated config

Unit-test everything here — this is the 80%-coverage target zone (PRD §18).
