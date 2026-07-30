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
| `secrets` | list of `{name, valueEnv}` | `[]` | See below |
| `env` | list of `{name, value, plaintext}` | `[]` | `value` is rejected if it looks like a credential — see below |
| `resources` | see below | `100m`/`128Mi` requests, `500m`/`512Mi` limits | — |
| `security` | see below | Kubernetes' own permissive defaults | — |
| `serviceType` | `ClusterIP` \| `NodePort` \| `LoadBalancer` | `ClusterIP` | — |

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

### `secrets`

Opt-in — real app secrets (a DB password, an API key), as opposed to `env`
below, which is free text and rejects anything that looks credential-shaped.

```yaml
app:
  secrets:
    - name: DB_PASSWORD          # env var name inside the container
      valueEnv: APP_DB_PASSWORD  # name of an env var in your shell, not a value
```

**`valueEnv` is an environment variable *name*, never the secret itself** —
same reasoning as `registry.usernameEnv`/`passwordEnv` above. `nexus deploy`
reads the actual value from that environment variable in your shell at
deploy time, and:

1. Creates (or updates, idempotently) a Secret named `<app.name>-secrets`,
   applied directly via `kubectl` — never rendered into the `k8s/` directory
   that gets committed.
2. References it on the Deployment via `valueFrom.secretKeyRef` (so the
   value itself never appears in any generated manifest, only a reference to
   a key in a Secret).

Missing the environment variable fails `nexus deploy` immediately with a
clear error naming which one (and `nexus doctor` catches it proactively).

This closes the plaintext-secrets-in-git gap for the common case — see
[FUTURE-SCOPE.md](https://github.com/kelyonn/nexus/blob/main/FUTURE-SCOPE.md)
for what a more thorough answer (Sealed Secrets/SOPS, for secrets encrypted
at rest in git rather than applied out-of-band) would involve.

### `env`'s credential guardrail

`app.env` values are otherwise free text, but `nexus.yaml` (and the `k8s/`
manifests `nexus deploy` commits) get pushed to your git remote — so an
`env` entry whose name looks credential-shaped (contains `PASS`, `SECRET`,
`TOKEN`, `API_KEY`, `PRIVATE_KEY`, `CREDENTIAL`, `DSN`, `DATABASE_URL`, or
`CONNECTION_STRING`) or whose value looks like a URL with embedded
credentials or a PEM-encoded key is rejected at `nexus.yaml` load time. Move
it to `app.secrets` instead. If it's a genuine false positive (an env var
that happens to match but isn't a credential — `MAX_TOKENS`, say), set
`plaintext: true` on that entry:

```yaml
app:
  env:
    - name: MAX_TOKENS
      value: "4096"
      plaintext: true
```

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

### `security`

```yaml
app:
  security:
    runAsNonRoot: false          # nexus init sets this to true for new apps
    runAsUser: null              # a specific UID, or leave to the image's own USER
    readOnlyRootFilesystem: false
```

Some container hardening is unconditional and always rendered on the
Deployment regardless of this section — `allowPrivilegeEscalation: false`,
dropping all Linux capabilities, a dedicated per-app `ServiceAccount` with
`automountServiceAccountToken: false`, and a `seccompProfile: RuntimeDefault`
— because no ordinary container needs any of that, so there's no tradeoff to
make configurable.

`runAsNonRoot`/`runAsUser`/`readOnlyRootFilesystem` are different: whether
they're safe to turn on depends entirely on the image. The schema default is
Kubernetes' own permissive default (all off), not a hardened one, because
Nexus can't know whether an arbitrary image declares a non-root `USER` or
expects to write to its own filesystem — flipping `runAsNonRoot: true` on an
image that doesn't support it fails the container outright
(`CreateContainerConfigError`) rather than degrading gracefully.
`nexus init` sets `runAsNonRoot: true` on every newly generated `nexus.yaml`,
so new apps opt in by default and the decision is visible, in writing, in
your own config either way.

Replicas >= 2 also get a `PodDisruptionBudget` (`maxUnavailable: 1`)
automatically — omitted at `replicas: 1`, where it would block every
voluntary disruption (a node drain, a cluster upgrade) forever instead of
protecting anything.

### `serviceType`

```yaml
app:
  serviceType: ClusterIP # or NodePort / LoadBalancer
```

Defaults to `ClusterIP`, reachable via the `kubectl port-forward` command
`nexus deploy` prints on success — that works identically everywhere, so
it's the default rather than `LoadBalancer` (which sits `<pending>` forever
on a bare Kind/Minikube cluster, and provisions a real, billed load balancer
per app on a real cloud one). See
[Exposing your app](exposing-your-app.md) for the full set of options,
including bringing your own Ingress.

## `platform`

| Field | Type | Default | Validation |
|---|---|---|---|
| `repoURL` | string | — (required) | Valid HTTPS or SSH git URL |
| `branch` | string | — (required) | Valid git branch name (letters, digits, `.`, `-`, `_`, `/`; no `..`, no leading `-`, no leading/trailing `/`) |
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
