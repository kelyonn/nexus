# tests/unit — fast, no-cluster tests

176 tests, **99% coverage** on `nexus_cli/core/` (target was 80%+, PRD §18).
Framework: `pytest` + `pytest-cov`. Everything mocks
`kubectl`/`helm`/`git`/the `kubernetes` SDK/ArgoCD — no cluster needed to run
these; see `tests/integration/` and `CLAUDE.md`'s "Testing this branch" for
live verification against a real cluster.

Covers:
- `nexus.yaml` parsing, validation rules (§9), defaults, and error messages
- Stack detection (Phase 1 signals: Node, Flask, generic fallback)
- Jinja2 templates render valid YAML for each shipped preset, including the
  **golden test** (rendered output ≡ the archived legacy manifests)
- `kubectl`/`helm`/`git`/`argocd` wrapper behavior: timeouts, error
  translation, idempotency (incl. real, unmocked git repos for branch-name
  edge cases a mock can't catch)
- Every command (`init`, `deploy`, `status`, `watch`, `destroy`): argument
  parsing, confirmation prompts, plan display, idempotency, partial-failure
  handling
