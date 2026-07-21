# commands/ — one module per CLI command

Each Nexus command gets its own module here, registered on the Typer app in
`main.py`.

- **Behavior spec:** the PRD §7 (exact requirements per command), §8 (exact terminal output to produce)
- **Build order (PRD §16):** `init` → `status` → `watch` → `deploy` → `destroy` (Phase 1, done), then `chaos`, `logs`, `upgrade`, `rollback`, `doctor` (Phase 2)

Ground rules: destructive commands always confirm (§7.5); `deploy` and
`destroy` are idempotent (§12); every error states what/why/fix (§12).

## What's here

- `init.py` — stack detection, config generation, `--stack` override
- `status.py` — replicas, ArgoCD sync/health, per-pod phase,
  ImagePullBackOff/CrashLoopBackOff detection with a context-aware fix
- `watch.py` — live pod events via the `kubernetes` SDK's watch stream
- `deploy.py` — preflight → dependency detection → plan → confirm → execute
  (install, apply, sync to git, register with ArgoCD) → verify
- `destroy.py` — typed-name confirmation, removes only this app's resources
