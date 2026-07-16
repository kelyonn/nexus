# examples — sample apps for demos and e2e tests

Planned (Phase 1): **`flask-demo/`** — promoted from `legacy/app/` (the
original demo's Flask color app: env-driven `VERSION`/`BG_COLOR`, `/healthz`
health endpoint, port 5050). It ships with a ready-made `nexus.yaml` and is
the app the integration tests deploy.

Each example = app source + `Dockerfile` + `nexus.yaml`, so a new user can run
the PRD's 10-minute quickstart (`nexus init` → `nexus deploy`) against
something real.
