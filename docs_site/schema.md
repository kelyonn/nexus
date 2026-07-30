# nexus.yaml schema

`nexus.yaml` has two top-level sections, `app` and `platform`, both
required. Validated with [Pydantic](https://docs.pydantic.dev/) — every rule
below is enforced, and a violation fails with a `what`/`why`/`fix` error
rather than a raw traceback. Unknown fields are rejected (`extra="forbid"`)
so a typo fails loudly instead of being silently ignored.

## `app`

| Field | Type | Default | Validation |
|---|---|---|---|
| `name` | string | — (required) | Lowercase alphanumeric and hyphens only, max 40 chars |
| `image` | string | — (required) | `registry/image:tag` — a tag is required |
| `port` | integer | — (required) | 1–65535 |
| `healthPath` | string | — (required) | Must start with `/` |
| `stack` | `node` \| `flask` \| `generic` \| `null` | `null` | — |
| `replicas` | integer | `2` | 1–20 |
| `imagePullPolicy` | `Always` \| `IfNotPresent` \| `Never` | `Always` | — |
| `metricsPath` | string \| `null` | `null` | Must start with `/` if set |
| `metricsPort` | integer \| `null` | `null` | 1–65535 if set |
| `registry` | object \| `null` | `null` | See below |
| `env` | list of `{name, value}` | `[]` | — |
| `resources` | see below | `100m`/`128Mi` requests, `500m`/`512Mi` limits | — |

### `imagePullPolicy`

`Always` is the safe default for a mutable `:latest`-style tag, but it's
exactly what makes the documented Minikube `ImagePullBackOff` fix
(`minikube image load` + redeploy) not work — the kubelet retries the
registry regardless of what's already loaded locally. Set `IfNotPresent` if
you're loading a locally-built image and want that fix to actually apply.
See [Troubleshooting](troubleshooting.md#imagepullbackoff-on-minikube).

### `metricsPath` / `metricsPort`

Opt-in (PRD §10.4). Unset means "this app doesn't expose Prometheus
metrics" — the honest default for an arbitrary containerized app, since
Nexus can't manufacture request-rate/error-rate/latency data your app never
emits. Setting `metricsPath` renders a `ServiceMonitor` so
kube-prometheus-stack's Prometheus scrapes your app directly, and three
extra Grafana dashboards (request rate, error rate, P95 latency) get
generated alongside the existing four. `metricsPort` defaults to `port` —
set it only if your app serves metrics on a different port than it serves
traffic.

The Grafana panels assume Prometheus's standard histogram/counter naming
convention (`<name>_total{status=...}`,
`<name>_duration_seconds_bucket{le=...}`) — check what your instrumentation
library actually emits before assuming it matches; `examples/flask-demo`
uses [`prometheus-flask-exporter`](https://github.com/rycus86/prometheus_flask_exporter),
whose real metric names are `flask_http_request_total` and
`flask_http_request_duration_seconds_bucket` (not the generic
`http_requests_total` some other libraries use).

### `registry`

Opt-in — closes the most common cause of `ImagePullBackOff`: a private
registry (ECR, GCR, a private GHCR/Docker Hub repo) that needs credentials
Kubernetes doesn't have. Unset means "this image is pullable without
credentials," the honest default for a public image or Minikube's local
cache.

```yaml
app:
  registry:
    server: ghcr.io                      # or your ECR/GCR registry host
    usernameEnv: REGISTRY_USERNAME       # name of an env var, not a value
    passwordEnv: REGISTRY_PASSWORD       # name of an env var, not a value
```

**`usernameEnv`/`passwordEnv` are environment variable *names*, never raw
credentials.** `nexus.yaml` gets committed to git — a real credential living
in it would recreate the exact "secret committed to git" problem GitOps
exists to avoid. `nexus deploy` reads the actual username/password from
those environment variables in your shell at deploy time, and:

1. Creates (or updates, idempotently) a `kubernetes.io/dockerconfigjson`
   Secret named `<app.name>-registry`, applied directly via `kubectl` —
   never rendered into the `k8s/` directory that gets committed.
2. Templates `imagePullSecrets: [{name: <app.name>-registry}]` onto the
   Deployment automatically.

Missing either environment variable fails `nexus deploy` immediately with a
clear error (and `nexus doctor` catches it proactively, before you even try
to deploy) — a silently-empty credential would instead produce a Secret
that *looks* configured but can't actually authenticate, discovered only
later as a confusing `ImagePullBackOff`.

### `resources`

```yaml
app:
  resources:
    requests:
      cpu: "100m"      # Kubernetes CPU quantity, e.g. 100m or 0.5
      memory: "128Mi"  # Kubernetes memory quantity, e.g. 128Mi
    limits:
      cpu: "500m"
      memory: "512Mi"
```

## `platform`

| Field | Type | Default | Validation |
|---|---|---|---|
| `repoURL` | string | — (required) | Valid HTTPS or SSH git URL |
| `branch` | string | — (required) | — |
| `monitoring` | boolean | `true` | — |
| `chaos` | boolean | `false` | — |
| `chaosSchedule` | string | `*/30 * * * *` | Valid 5-field cron expression |

`branch` must match the branch your working directory is actually on —
ArgoCD tracks `platform.branch`, and a mismatch soft-skips the git-sync step
rather than aborting. See
[Troubleshooting](troubleshooting.md#branch-mismatch-soft-skip).

Running more than one environment (staging/prod) from separate `nexus.yaml`
files? `branch` is the field that actually keeps them from colliding — see
[Multiple environments](multi-environment.md).

## Full example

From `examples/flask-demo/nexus.yaml`:

```yaml
app:
  name: nexus-app
  image: kelyonnnn17/nexus-app:v1
  port: 5050
  healthPath: /healthz
  stack: flask
  replicas: 2
  env:
    - name: VERSION
      value: v1
    - name: BG_COLOR
      value: blue

platform:
  repoURL: https://github.com/kelyonn/nexus.git
  branch: cli-platform
  monitoring: true
  chaos: false
```
