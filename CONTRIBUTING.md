# Contributing to Nexus

Thanks for considering it. This project is young, and the fastest way to
help right now is real usage — bug reports, edge cases hit against a real
cluster, and small fixes matter more than large ones.

## Before you start

- **Not yet published to PyPI.** Install from source — see the
  [README](README.md#try-it) or the
  [docs site's install guide](https://kelyonn.github.io/nexus/install/).
- **Read [`docs_site/architecture.md`](docs_site/architecture.md) first** if
  you're touching `core/` — it explains why commands stay thin and all the
  actual logic lives in `nexus_cli/core/`, which is the property that keeps
  the CLI and the dashboard from silently disagreeing about anything.
- **`legacy/` is read-only.** It's the archived, original hand-written demo
  that every Jinja2 template in `nexus_cli/templates/` is derived from —
  never modify it, and see `nexus_cli/templates/README.md` for the mapping
  if you're adding or changing a template.

## Setup

```bash
git clone https://github.com/kelyonn/nexus.git && cd nexus
python3 -m venv venv && source venv/bin/activate
pip install -e ".[dev,dashboard]"
```

If you're touching the dashboard frontend, also see
`dashboard/frontend/README.md` for its two build modes.

## Before opening a PR

Run the same gate CI runs:

```bash
ruff check .
mypy nexus_cli dashboard/backend
pytest -q --cov=nexus_cli.core --cov-report=term-missing --cov-fail-under=80
```

If you touched `dashboard/frontend/`:

```bash
cd dashboard/frontend
npx eslint .
npx tsc --noEmit
NEXUS_STATIC_EXPORT=1 npm run build
```

**Live-verify against a real cluster before claiming something works.**
Nothing in this project's history has shipped on unit tests alone — every
fix and feature here was proven against a real Minikube or Kind cluster
first (see `docs_site/troubleshooting.md` for examples of real bugs unit
tests alone wouldn't have caught: an ArgoCD version quirk, a Chaos Mesh
webhook race, a git branch-mismatch edge case). A quick path:

```bash
minikube start --driver=docker
cd examples/flask-demo
nexus deploy   # ... exercise whatever you changed ... 
nexus destroy
```

## Commit style

Concise, imperative subject with a type prefix (`feat:`, `fix:`, `refactor:`,
`docs:`, `chore:`); the body explains *why*, not just what changed. No
AI-co-authorship trailers, please — commits should be attributable to a
human author.

## Reporting bugs / requesting features

Use the issue templates — they ask for the specific things that make a
Kubernetes-adjacent bug report actionable (cluster type, `nexus --version`,
the actual command and output).

## Scope boundaries worth knowing before you propose something

- **No Ingress support.** Apps are reachable via `LoadBalancer`/port-forward,
  not a domain name — a deliberate scope boundary, not an oversight.
- **No opt-in telemetry**, for now — revisit once there's a real user base
  to learn from.
- Stack auto-detection (`nexus init`) currently covers Node, Flask, and a
  generic fallback. Django/Go detectors are a known v2 item, not started.

See [FUTURE-SCOPE.md](FUTURE-SCOPE.md) for bigger ideas that are real but
deliberately not started — secret management, a real multi-environment
schema, dashboard log streaming — each with the design questions it needs
answered first. If you want to pick one up, start there.

If you're unsure whether something fits, open an issue to discuss before
sending a large PR — much easier to redirect early than to review a big
diff against a still-shifting scope.
