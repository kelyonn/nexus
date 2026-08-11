# Install & quickstart

## Requirements

- Python 3.10+
- Docker
- [Minikube](https://minikube.sigs.k8s.io/) or [Kind](https://kind.sigs.k8s.io/)

Nexus shells out to `kubectl` and `helm` for most operations, and uses the
`kubernetes` Python SDK for streaming commands (`nexus watch`, `nexus logs`).
Both `kubectl` and `helm` need to be on your `PATH`.

## Install

```bash
pip install nexus-gitops
```

That's the whole install for using Nexus against your own app. The
walkthrough below additionally clones this repo to use its bundled example
app — for that, or for contributing, use an editable install from a
checkout instead:

```bash
git clone https://github.com/kelyonn/nexus.git && cd nexus

python3 -m venv venv && source venv/bin/activate
pip install -e ".[dev]"
```

## Start a cluster

```bash
minikube start --driver=docker
```

If `kubectl get nodes` fails with EOF/TLS errors afterward, run
`minikube update-context && minikube start --driver=docker` again — this is
a known Minikube quirk, not a Nexus problem. See
[Troubleshooting](troubleshooting.md) for more Minikube-specific notes.

## The golden path

```bash
cd examples/flask-demo
nexus deploy      # installs ArgoCD + monitoring, deploys the app — type y
nexus status        # replicas, pods, ArgoCD sync/health
nexus open           # port-forwards the app and opens it in your browser, Ctrl+C to stop
nexus watch          # live pod events, Ctrl+C to stop
nexus logs            # tail every pod's logs, prefixed by pod name
nexus chaos run        # kill one pod, watch it recover
nexus doctor             # environment diagnostics — every problem, with a fix
nexus destroy              # type the app name to confirm
```

`nexus deploy` never opens the app for you — it's a one-shot, idempotent
command, and a background tunnel left running after it exits would collide
with your next `nexus deploy`. `nexus open` is the dedicated way to view it
(on Minikube, `minikube service <app-name> -n <app-name>` also works and
skips the extra command) — see [Exposing your app](exposing-your-app.md) for
the other options.

`nexus deploy` is safe to run more than once — it skips components that are
already installed and never duplicates resources. See the
[command reference](commands.md) for every flag, and the
[schema reference](schema.md) for what goes in `nexus.yaml`.

`nexus upgrade --image <tag>` and `nexus rollback` also exist but need a real
git remote to push to (not `examples/flask-demo`'s own repo — see the repo's
`INSTALLATION.md` if you want to try those against a throwaway repo).

## The dashboard

```bash
pip install -e ".[dashboard]"   # fastapi/uvicorn — not in the base install
nexus dashboard                  # opens the browser, Ctrl+C to stop
```

No Node.js needed — the frontend ships as a static export baked into the
package. Needs at least one app deployed (the golden path above) to show
anything on the Overview grid.

`nexus dashboard` automatically port-forwards Prometheus and Grafana if it
finds them on the cluster — no manual `kubectl port-forward` needed. Prometheus
feeds the App Detail page's own CPU/memory/replicas/restarts sparklines
directly (native inline SVG, not Grafana); Grafana itself is one click away
via "Open Grafana ↗", which deep-links straight to the app's one
consolidated dashboard, and `nexus dashboard` prints the admin login right
then so that click isn't a dead end.

Want the request-rate / error-rate / P95-latency panels too? Set
`app.metricsPath` in `nexus.yaml` — see the
[schema reference](schema.md#metricspath-metricsport) for what your app
needs to expose.
