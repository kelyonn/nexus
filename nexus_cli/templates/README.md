# templates/ — Jinja2 manifest templates

The YAML that `nexus deploy` renders from `nexus.yaml`. All 7 built, derived
from the archived demo's manifests by parameterizing them (PRD §0's mapping,
below) — none invented from scratch.

| Template | Derived from |
|---|---|
| `deployment.yaml.j2` | `legacy/k8s/deployment.yaml` |
| `service.yaml.j2` | `legacy/k8s/service.yaml` |
| `namespace.yaml.j2` | `legacy/k8s/namespace.yaml` |
| `argocd-app.yaml.j2` | `legacy/application.yaml` |
| `prometheus-rules.yaml.j2` | `legacy/monitoring/prometheus-rule-*.yaml` |
| `grafana-dashboard.yaml.j2` | `legacy/monitoring/grafana-dashboards-configmap.yaml` |
| `podchaos.yaml.j2` | `legacy/chaos/pod-kill.yaml` + `pod-kill-schedule.yaml` |

Parameterized: `nexus-app` → `{{ app.name }}` · image → `{{ app.image }}` ·
`5050` → `{{ app.port }}` · `/healthz` → `{{ app.healthPath }}` · `replicas: 2`
→ `{{ app.replicas }}`. Every template renders valid YAML for every stack
preset, verified by the **golden test** (`tests/unit/test_render.py` — rendered
output reproduces the legacy manifests) plus the two deliberate, documented
deviations (`app.name` drives both namespace and resource name; chaos defaults
to `mode: one`, not legacy's `fixed-percent: 50`).
