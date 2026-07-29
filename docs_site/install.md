# Install & quickstart

## Requirements

- Python 3.10+
- Docker
- [Minikube](https://minikube.sigs.k8s.io/) or [Kind](https://kind.sigs.k8s.io/)

Nexus shells out to `kubectl` and `helm` for most operations, and uses the
`kubernetes` Python SDK for streaming commands (`nexus watch`, `nexus logs`).
Both `kubectl` and `helm` need to be on your `PATH`.

## Install from source

Not yet published to PyPI — install from a checkout:

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
nexus watch          # live pod events, Ctrl+C to stop
nexus logs            # tail every pod's logs, prefixed by pod name
nexus chaos run        # kill one pod, watch it recover
nexus doctor             # environment diagnostics — every problem, with a fix
nexus destroy              # type the app name to confirm
```

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

`nexus dashboard` automatically port-forwards Grafana and Prometheus if it
finds them on the cluster, so the Metrics panels and CPU/memory sparklines on
the App Detail page just work — no manual `kubectl port-forward` needed.

Want the request-rate / error-rate / P95-latency panels too? Set
`app.metricsPath` in `nexus.yaml` — see the
[schema reference](schema.md#metricspath-metricsport) for what your app
needs to expose.
