# Command reference

Every flag below is copied straight from `--help` output, not written from
memory — run `nexus <command> --help` yourself any time to confirm it's
still accurate.

## `nexus init`

Detect your app's stack and generate a pre-filled `nexus.yaml`.

| Flag | Description |
|---|---|
| `--stack <str>` | Force a stack preset (`node`, `flask`, `generic`) instead of auto-detecting. |

## `nexus deploy`

Install missing platform components, apply manifests, sync to git, register
with ArgoCD.

| Flag | Description |
|---|---|
| `--config <str>` | Path to the `nexus.yaml` to read. Default: `nexus.yaml` |
| `-y`, `--yes` | Skip the confirmation prompt. |

Idempotent (PRD §12) — running it again skips components already installed
and never duplicates resources.

## `nexus status`

Show deployment health: replicas, ArgoCD sync/health, and pod status.

| Flag | Description |
|---|---|
| `--config <str>` | Path to the `nexus.yaml` to read. Default: `nexus.yaml` |

## `nexus watch`

Stream pod lifecycle events for the app's namespace until Ctrl+C.

| Flag | Description |
|---|---|
| `--config <str>` | Path to the `nexus.yaml` to read. Default: `nexus.yaml` |

## `nexus logs`

Print each pod's log tail, prefixed with the pod name.

| Flag | Description |
|---|---|
| `--config <str>` | Path to the `nexus.yaml` to read. Default: `nexus.yaml` |
| `--tail <int>` | Number of lines to show per pod. Default: `50` |
| `-f`, `--follow` | Stream logs continuously from every pod until Ctrl+C, like `kubectl logs -f`. |

`--follow` streams every matching pod concurrently (one thread per pod),
interleaved and prefixed the same way as the default snapshot output.

## `nexus doctor`

Diagnose the environment: tool installs, cluster access, RBAC, config, and
git. Every problem it reports names a fix (PRD §12).

| Flag | Description |
|---|---|
| `--config <str>` | Path to the `nexus.yaml` to read, if present. Default: `nexus.yaml` |

## `nexus upgrade`

Bump the app's image, commit + push through git, and roll out via ArgoCD.

| Flag | Description |
|---|---|
| `--image <str>` | **Required.** New image, e.g. `myrepo/app:v2`. |
| `--config <str>` | Path to the `nexus.yaml` to read. Default: `nexus.yaml` |
| `--dry-run` | Show what would change without committing. |
| `-y`, `--yes` | Skip the branch-mismatch confirmation. |

## `nexus rollback`

Roll back the app's image through git — revert the last change, or restore
the state from a specific commit with `--to-commit`.

| Flag | Description |
|---|---|
| `--to-commit <str>` | Restore the `nexus.yaml` image from this commit. |
| `--list` | Show recent Nexus-authored image changes. |
| `--config <str>` | Path to the `nexus.yaml` to read. Default: `nexus.yaml` |
| `--dry-run` | Show what would change without committing. |
| `-y`, `--yes` | Skip the branch-mismatch and rollback confirmations. |

## `nexus destroy`

Remove this app's namespace, ArgoCD Application, and monitoring resources.
Requires typing the app name to confirm (PRD §7.5) — ArgoCD, Prometheus, and
Chaos Mesh themselves are left installed.

| Flag | Description |
|---|---|
| `--config <str>` | Path to the `nexus.yaml` to read. Default: `nexus.yaml` |
| `--dry-run` | Show what would be deleted without deleting anything, or prompting. |

## `nexus chaos run`

Trigger a one-shot PodChaos experiment against the app's pods.

| Flag | Description |
|---|---|
| `--config <str>` | Path to the `nexus.yaml` to read. Default: `nexus.yaml` |
| `--kill-all` | Kill all pods simultaneously instead of just one. |
| `--action <str>` | Chaos type: `pod-kill`, `pod-failure`, `container-kill`. Default: `pod-kill` |

## `nexus chaos schedule enable` / `disable`

Enable or disable the recurring PodChaos schedule (`platform.chaosSchedule`
in `nexus.yaml`, a standard 5-field cron expression).

- `nexus chaos schedule enable` — apply the recurring schedule, resuming it
  if it was suspended.
- `nexus chaos schedule disable` — suspend the recurring schedule (does not
  delete it).

Both take `--config <str>` (default: `nexus.yaml`).

## `nexus dashboard`

Launch the local dashboard and open it in your browser. No flags — see
[Install & quickstart](install.md#the-dashboard) for what it needs and
[Architecture](architecture.md#the-dashboard) for how it's put together.
