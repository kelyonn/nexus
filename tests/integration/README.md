# tests/integration — against a real cluster

Spec: the PRD §18. Runs against Kind or Minikube
(locally and in GitHub Actions).

Covers:
- E2E: `nexus init` → `deploy` → `status` → `destroy` on the flask-demo example
- Idempotency: `deploy` twice (no errors, no duplicates); `destroy` twice (clean no-op)
- Preflight failures: missing kubectl / missing helm / unreachable cluster
- Partial-failure: a failed step is reported and the state is recoverable
- Chaos: `nexus chaos run` → pod recovery (gated job; Chaos Mesh on Kind can be flaky)
