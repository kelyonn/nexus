# Multiple environments (staging / prod)

There's no `environments:` block in `nexus.yaml` — every command already
takes `--config <path>`, so the lightweight way to run more than one
environment today is **one `nexus.yaml` per environment**, deployed with
`--config`:

```bash
nexus deploy --config nexus.staging.yaml
nexus deploy --config nexus.prod.yaml
```

This works, but two fields in each file have to be set correctly or one
environment will silently clobber another. Read this whole page before
setting one up — the failure mode isn't an error message, it's ArgoCD
quietly deploying the wrong environment's config.

## The constraint that actually matters: `platform.branch`

`nexus deploy` renders manifests and commits them to a **fixed path**,
`<cwd>/k8s/`, on whatever `platform.branch` says (see
[Architecture](architecture.md#gitops-loop)). That path isn't
configurable — it's hardcoded on both sides (the git-sync step and the
ArgoCD `Application`'s `spec.source.path`) so the two can never drift apart.

That means **two environments must use two different `platform.branch`
values**, or the second `nexus deploy` overwrites the first environment's
manifests in git — same path, same directory, on whatever branch was
actually checked out. This is true even if the two environments target
completely separate clusters: if both `nexus.yaml` files point ArgoCD at the
same `repoURL` + `branch` + `k8s/` path, both ArgoCD instances sync the
*same* content, so "separate clusters" doesn't save you here — separate
branches (or separate repos) is what actually isolates them.

```yaml
# nexus.staging.yaml
platform:
  repoURL: https://github.com/you/your-app.git
  branch: staging
---
# nexus.prod.yaml
platform:
  repoURL: https://github.com/you/your-app.git
  branch: main
```

And because `nexus deploy` soft-skips the git-sync step whenever your
actual checked-out branch doesn't match `platform.branch` (see
[Troubleshooting](troubleshooting.md#branch-mismatch-soft-skip)), you need
to check out the matching branch before each deploy:

```bash
git checkout staging && nexus deploy --config nexus.staging.yaml
git checkout main     && nexus deploy --config nexus.prod.yaml
```

## The second thing to get right: `app.name`

`app.name` becomes both the Kubernetes **namespace** and the ArgoCD
**Application name** (`nexus_cli/templates/namespace.yaml.j2` and
`argocd-app.yaml.j2`) — there's no separate namespace field. If staging and
prod share a cluster and use the *same* `app.name`, they'll collide: same
namespace, same ArgoCD `Application` object, one environment's Deployment
silently overwriting the other's.

- **Same cluster, one `kubectl` context for both:** give each environment a
  distinct `app.name` (`myapp-staging` / `myapp`, or similar).
- **Separate clusters / separate `kubectl` contexts:** `app.name` can stay
  the same — the namespace and Application name only need to be unique
  *within* a given cluster — but you still need the distinct `platform.branch`
  from above, and you're responsible for switching `kubectl` context (`kubectl
  config use-context <env>`) to the right cluster before each deploy; Nexus
  always operates against whatever context is currently active.

## What you get from this today

- Independent `nexus deploy`/`status`/`watch`/`logs`/`upgrade`/`rollback` per
  environment, just by passing the matching `--config`.
- Independent replica counts, resource limits, image tags, `metricsPath`,
  chaos schedule, etc. — every field in the [schema](schema.md) can differ
  per environment file.
- Independent GitOps history per environment (separate branches means
  separate `nexus rollback`/sync-log history too).

## What this doesn't give you

- A single `nexus.yaml` with per-environment overrides (the `environments:`
  block some tools use) — you maintain two full files, with the duplication
  that implies. A real overrides/inheritance schema is tracked as future
  work — see the repo's `FUTURE-SCOPE.md`.
- Any automatic environment promotion (`nexus promote staging prod` or
  similar) — you're pushing an image tag bump to each branch yourself via
  `nexus upgrade --config nexus.<env>.yaml`.
