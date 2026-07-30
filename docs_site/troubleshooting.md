# Troubleshooting

Real problems hit during development and live verification against
Minikube/Kind — not a hypothetical FAQ. Each one links to the code that
fixes or reports it.

## `ImagePullBackOff` on Minikube

**Symptom:** `nexus status` shows `ImagePullBackOff` or `ErrImagePull` for a
locally-built image you loaded with `minikube image load`.

**Cause:** `app.imagePullPolicy` defaults to `Always` (the safe default for
a mutable `:latest`-style tag). Under `Always`, the kubelet always re-checks
the registry regardless of what's already loaded locally — `minikube image
load` alone does nothing.

**Fix:** set `app.imagePullPolicy: IfNotPresent` in `nexus.yaml`, then
re-run `minikube image load <image>` and redeploy. `nexus status` tells you
this directly (`core/status.py`'s `image_pull_fix()` is context-aware: it
checks whether you're on a Minikube context and what `imagePullPolicy` is
currently set to before suggesting a fix).

## `ImagePullBackOff` / `401 Unauthorized` pulling a private image

**Symptom:** `kubectl describe pod` shows something like `pull access
denied` or `401 Unauthorized`, not a plain "not found" — the image exists,
but Kubernetes has no credentials for the registry it's in.

**Cause:** by default Nexus assumes your image is pullable without
credentials (a public image, or Minikube's local cache). A private registry
(ECR, GCR, a private GHCR/Docker Hub repo) needs an `imagePullSecrets`
entry Nexus doesn't create unless you ask it to.

**Fix:** set `app.registry` in `nexus.yaml` — see the
[schema reference](schema.md#registry). Note it takes environment variable
*names*, not the credentials themselves; set those variables in your shell
before running `nexus deploy`. `nexus doctor` catches a missing credential
env var before you even get to `nexus deploy`.

## ArgoCD reports `health: Progressing` forever on a fully healthy app

**Symptom:** `nexus deploy`/`upgrade`/`rollback` wait the full sync timeout
and then print a "did not become Synced + Healthy" error — even though
`kubectl get pods` shows everything `Running` and `nexus status` looks fine.

**Cause:** a real quirk on the ArgoCD version `nexus deploy` currently
installs (v3.4.5 at time of writing): `health` can stay `Progressing`
indefinitely for a Deployment Kubernetes itself reports fully `Available`.
This was flagged twice during live verification (Week 1 and Week 2) before
being fixed.

**Fix:** already handled — `argocd.wait_for_healthy()` cross-checks ground
truth via the Deployment's own replica counts when `sync == Synced` and
`health == Progressing` (never `Degraded`/`Missing`): if `available ==
desired` and `desired > 0`, it treats the rollout as genuinely healthy and
returns, printing an honest note that ArgoCD's own health check disagrees.
If you still see the timeout error, the Deployment itself isn't actually
ready — check `kubectl -n argocd describe application <name>` for what's
really blocking it.

## Branch-mismatch soft-skip

**Symptom:** `nexus deploy` prints:

```
Current git branch ('main') does not match platform.branch ('cli-platform').

ArgoCD tracks platform.branch — committing here would desync it.

Run `git checkout cli-platform`, or update platform.branch in nexus.yaml to match.
```

...and `nexus status` afterward shows `Sync: Unknown`.

**Cause:** this is by design, not a bug — see `deploy.py`'s module
docstring. `platform.branch` is what ArgoCD tracks; committing rendered
manifests to a *different* branch than the one you're actually on would
desync the two, so the git-sync step warns and skips rather than silently
doing the wrong thing. Your app's manifests are still applied directly via
`kubectl` either way — only the GitOps commit/push is skipped.

**Fix:** either `git checkout <platform.branch>` before deploying, or edit
`platform.branch` in `nexus.yaml` to match your actual branch. For `sync:
Synced` to show up for real, `platform.repoURL` also needs to be a real
remote your cluster can reach — `localhost` doesn't work, since ArgoCD runs
inside the cluster.

## Chaos Mesh admission-webhook race

**Symptom:** the very first `nexus chaos run` or `nexus chaos schedule
enable` right after a fresh `nexus deploy` (with `platform.chaos: true`)
fails with:

```
Error from server (InternalError): ... failed calling webhook "vauth.kb.io"
```

**Cause:** Chaos Mesh's admission webhook server isn't always serving yet by
the time Helm reports the release ready — a genuine race hit during live
verification (install took ~14s that run, versus ~90s in earlier manual
runs, so the timing window was real).

**Fix:** already handled — `_with_webhook_retry()` in `commands/chaos.py`
retries only that specific error, up to 20s every 2s, around the three
mutating calls that touch chaos-mesh resources. Anything else re-raises
immediately. If you hit this and it doesn't clear within 20s, something
else is actually wrong — check `kubectl -n chaos-mesh get pods` for a
crashing webhook server.

## Minikube `kubectl get nodes` fails with EOF/TLS errors

**Cause:** a known Minikube quirk, most often after Docker Desktop restarts
or the host sleeps.

**Fix:**

```bash
minikube update-context && minikube start --driver=docker
```

If `minikube start` itself won't come up, check `docker info` — if that
fails too, `open -a Docker` (macOS) and wait ~10–20s before retrying.

## Dashboard: "Dashboard frontend isn't built"

**Symptom:** `nexus dashboard` fails immediately with this error, from a
repo checkout (not a `pip install`).

**Cause:** the dashboard now ships as a static export
(`dashboard/frontend/out/`) rather than requiring a running `next dev`
server — see [Architecture](architecture.md#the-dashboard). A checkout
needs that export built once before the first run.

**Fix:**

```bash
cd dashboard/frontend
NEXUS_STATIC_EXPORT=1 npm ci && NEXUS_STATIC_EXPORT=1 npm run build
```

A release wheel installed via `pip` bundles this automatically — if you hit
this error from a `pip install`, that's a packaging bug, please file an
issue.
