# templates/ — Jinja2 manifest templates

The YAML that `nexus deploy` renders from `nexus.yaml`. 7 of the 9 are
derived from the archived demo's manifests by parameterizing them (PRD §0's
mapping, below) — nothing there invented from scratch. The remaining 2
(`serviceaccount.yaml.j2`, `pdb.yaml.j2`) have no `legacy/` equivalent —
`legacy/k8s/` predates a dedicated ServiceAccount and PodDisruptionBudget the
same way it predates the `resources:` block below, so they're documented
deviations rather than parameterized legacy content. See `CHANGELOG.md`.

| Template | Derived from |
|---|---|
| `deployment.yaml.j2` | `legacy/k8s/deployment.yaml` |
| `service.yaml.j2` | `legacy/k8s/service.yaml` |
| `namespace.yaml.j2` | `legacy/k8s/namespace.yaml` |
| `serviceaccount.yaml.j2` | *(new — no legacy equivalent; see above)* |
| `pdb.yaml.j2` | *(new — no legacy equivalent; renders only when `app.replicas >= 2`)* |
| `argocd-app.yaml.j2` | `legacy/application.yaml` |
| `prometheus-rules.yaml.j2` | `legacy/monitoring/prometheus-rule-*.yaml` |
| `grafana-dashboard.yaml.j2` | `legacy/monitoring/grafana-dashboards-configmap.yaml` |
| `podchaos.yaml.j2` | `legacy/chaos/pod-kill.yaml` + `pod-kill-schedule.yaml` |

Parameterized: `nexus-app` → `{{ app.name }}` · image → `{{ app.image }}` ·
`5050` → `{{ app.port }}` · `/healthz` → `{{ app.healthPath }}` · `replicas: 2`
→ `{{ app.replicas }}`. Every template renders valid YAML for every stack
preset, verified by the **golden test** (`tests/unit/test_render.py` — rendered
output reproduces the legacy manifests) plus the deliberate, documented
deviations: `app.name` drives both namespace and resource name; chaos defaults
to `mode: one`, not legacy's `fixed-percent: 50`; `deployment.yaml.j2` carries
pod-hardening (`securityContext`, `serviceAccountName`, `topologySpreadConstraints`,
`startupProbe`) legacy never had.
