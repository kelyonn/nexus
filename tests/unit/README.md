# tests/unit — fast, no-cluster tests

Spec: the PRD §18. Framework: `pytest` + `pytest-cov`
(target 80%+ on `nexus_cli/core/`).

Covers:
- `nexus.yaml` parsing, validation rules (§9), defaults, and error messages
- Stack detection (Phase 1 signals only: Node, Flask, generic fallback)
- Jinja2 templates render valid YAML for each shipped preset
- CLI argument parsing for every command and flag
