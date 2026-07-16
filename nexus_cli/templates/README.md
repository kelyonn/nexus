# templates/ — Jinja2 manifest templates

The YAML that `nexus deploy` renders from `nexus.yaml`. **Derive these from
the archived demo's manifests by parameterizing them — do not write from
scratch.** Full mapping table: [docs/PRD.md](../../docs/PRD.md) §0.

| Template (to create) | Derived from |
|---|---|
| `deployment.yaml.j2` | `legacy/k8s/deployment.yaml` |
| `service.yaml.j2` | `legacy/k8s/service.yaml` |
| `namespace.yaml.j2` | `legacy/k8s/namespace.yaml` |
| `argocd-app.yaml.j2` | `legacy/application.yaml` |
| `prometheus-rules.yaml.j2` | `legacy/monitoring/prometheus-rule-*.yaml` |
| `grafana-dashboard.yaml.j2` | `legacy/monitoring/grafana-dashboards-configmap.yaml` |
| `podchaos.yaml.j2` | `legacy/chaos/pod-kill.yaml` + `pod-kill-schedule.yaml` |

Parameterize: `nexus-app` → `{{ app.name }}` · image → `{{ app.image }}` ·
`5050` → `{{ app.port }}` · `/healthz` → `{{ app.healthPath }}` · `replicas: 2`
→ `{{ app.replicas }}`. Every template must render valid YAML for every stack
preset (tested in `tests/unit/`).
