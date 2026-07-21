# examples — sample apps for demos and e2e tests

**`flask-demo/`** — promoted from `legacy/app/` (the original demo's Flask
color app: env-driven `VERSION`/`BG_COLOR`, `/healthz` health endpoint, port
5050). Ships with a working `nexus.yaml` and is used as:

- the golden-test fixture (`tests/unit/test_render.py` — rendered templates
  reproduce the archived legacy manifests)
- the app used for live Minikube verification of every command

Each example = app source + `Dockerfile` + `nexus.yaml`, so a new user can run
the PRD's 10-minute quickstart (`nexus init` → `nexus deploy`) against
something real.
