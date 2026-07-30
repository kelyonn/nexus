## What & why

<!-- What changed, and why — link an issue if there is one. -->

## How was this verified?

<!--
Unit tests alone haven't been enough for anything in this project's history
— every fix/feature so far was proven against a real Minikube or Kind
cluster (see docs_site/troubleshooting.md for examples of bugs that only
showed up live). If this change touches nexus_cli/core, nexus_cli/commands,
dashboard/backend, or the Jinja2 templates, describe what you actually ran
against a real cluster, not just which tests pass.
-->

- [ ] `ruff check .` / `mypy nexus_cli dashboard/backend` / `pytest -q` all pass
- [ ] If touching `dashboard/frontend/`: `eslint` / `tsc --noEmit` /
      `NEXUS_STATIC_EXPORT=1 npm run build` all pass
- [ ] Live-verified against a real cluster (describe how below), or this is
      docs/tests-only and doesn't need it

<!-- describe live verification here -->

## Anything reviewers should look at closely?

<!-- e.g. "this touches upgrade/rollback, which run git commit/push on user repos" -->
