"""app.secrets automation — real app secrets (DB passwords, API keys), as
opposed to app.env's free-text-but-credential-rejecting environment
variables.

Modeled directly on ``core/registry.py``'s imagePullSecret automation: each
``app.secrets`` entry names an environment variable to read the actual
secret value from at deploy time (``core/config.py``'s ``SecretVar``) —
``nexus.yaml`` never holds the value itself, since it gets committed to git
(``commands/deploy.py``'s ``sync_manifests_to_git``). The Secret this module
creates is applied imperatively via ``kubectl``, the same way the
imagePullSecret and ArgoCD/Prometheus/Chaos Mesh themselves are — it is
never rendered into ``k8s/`` or committed.

One difference from the registry secret: this Secret can hold an arbitrary
number of keys, so it's built one ``--from-file=<key>=<path>`` argument per
entry (in one ``kubectl create secret generic`` call) rather than the
registry secret's single ``.dockerconfigjson`` file — still no
``--from-literal=...``, for the same argv-exposure reason documented in
``apply_pull_secret`` below.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from nexus_cli.core import kubectl
from nexus_cli.core.config import AppConfig
from nexus_cli.core.output import NexusError


def resolve_values(app: AppConfig) -> dict[str, str]:
    """Read the actual secret values from the env vars nexus.yaml names.

    Reports *every* missing env var in one error (not just the first) — the
    same reasoning as ``registry.resolve_credentials``: a user fixing one at
    a time via repeated failed `nexus deploy` runs is worse than seeing the
    whole list up front.
    """
    missing: list[str] = []
    values: dict[str, str] = {}
    for entry in app.secrets:
        value = os.environ.get(entry.valueEnv, "")
        if not value:
            missing.append(entry.valueEnv)
        else:
            values[entry.name] = value
    if missing:
        raise NexusError(
            what=f"Secret env var(s) not set: {', '.join(missing)}.",
            why=(
                "app.secrets in nexus.yaml names environment variables to read secret "
                "values from at deploy time — nexus.yaml itself never holds them."
            ),
            fix=f"Set {' and '.join(missing)} in your shell before running `nexus deploy`.",
        )
    return values


def apply_app_secret(app: AppConfig) -> None:
    """Create or update the app's Secret from app.secrets (idempotent upsert
    — same dry-run-then-apply pattern used for every other resource Nexus
    applies, including the imagePullSecret).

    A no-op when app.secrets is unset (most apps). Each value goes into its
    own short-lived, owner-only-readable temp file and reaches kubectl via
    ``--from-file=<key>=<path>``, not ``--from-literal=<key>=<value>`` — the
    latter leaves the raw value visible to anything that can read this
    process's argv (``ps aux``, ``/proc/<pid>/cmdline``) for as long as the
    process runs, same reasoning as ``registry.apply_pull_secret``.
    """
    if not app.secrets:
        return
    values = resolve_values(app)

    tmp_paths: list[Path] = []
    try:
        from_file_args = []
        for key, value in values.items():
            # tempfile.mkstemp creates the file mode 0600 (owner read/write
            # only) from the moment it exists — no window where it's briefly
            # more open, same as apply_pull_secret's single temp file.
            fd, tmp_path_str = tempfile.mkstemp(prefix="nexus-secret-", suffix=".txt")
            tmp_path = Path(tmp_path_str)
            tmp_paths.append(tmp_path)
            with os.fdopen(fd, "w") as f:
                f.write(value)
            from_file_args.append(f"--from-file={key}={tmp_path}")

        result = kubectl.run(
            [
                "create",
                "secret",
                "generic",
                app.secret_name,
                *from_file_args,
                "-n",
                app.name,
                "--dry-run=client",
                "-o",
                "yaml",
            ]
        )
        kubectl.apply_manifest(result.stdout)
    finally:
        for tmp_path in tmp_paths:
            tmp_path.unlink(missing_ok=True)
