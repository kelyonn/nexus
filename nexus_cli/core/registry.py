"""imagePullSecrets automation for private registries.

Registry credentials never appear in ``nexus.yaml`` — only the *names* of
environment variables to read them from at deploy time
(``app.registry.usernameEnv``/``passwordEnv``, see ``core/config.py``'s
``RegistryConfig``). ``nexus.yaml`` gets committed to git
(``commands/deploy.py``'s ``sync_manifests_to_git``); a raw credential
living there would recreate the exact "secret committed to git" problem
GitOps exists to avoid. The Secret this module creates is applied
imperatively via ``kubectl``, the same way ArgoCD/Prometheus get installed —
it is never rendered into ``k8s/`` or committed.
"""

from __future__ import annotations

import base64
import json
import os
import tempfile
from pathlib import Path

from nexus_cli.core import kubectl
from nexus_cli.core.config import AppConfig
from nexus_cli.core.output import NexusError


def resolve_credentials(app: AppConfig) -> tuple[str, str]:
    """Read the actual username/password from the env vars nexus.yaml names.

    Fails clearly (what/why/fix) if either is unset or empty — a silently
    empty credential would produce a Secret that *looks* configured but
    can't authenticate, a worse failure mode (a confusing ImagePullBackOff
    later) than refusing up front.
    """
    assert app.registry is not None  # callers only invoke this when set
    username = os.environ.get(app.registry.usernameEnv, "")
    password = os.environ.get(app.registry.passwordEnv, "")
    missing = [
        env_name
        for env_name, value in (
            (app.registry.usernameEnv, username),
            (app.registry.passwordEnv, password),
        )
        if not value
    ]
    if missing:
        raise NexusError(
            what=f"Registry credential env var(s) not set: {', '.join(missing)}.",
            why=(
                "app.registry in nexus.yaml names environment variables to read "
                "credentials from at deploy time — nexus.yaml itself never holds them."
            ),
            fix=f"Set {' and '.join(missing)} in your shell before running `nexus deploy`.",
        )
    return username, password


def _docker_config_json(server: str, username: str, password: str) -> str:
    auth = base64.b64encode(f"{username}:{password}".encode()).decode()
    return json.dumps(
        {"auths": {server: {"username": username, "password": password, "auth": auth}}}
    )


def apply_pull_secret(app: AppConfig) -> None:
    """Create or update the app's imagePullSecret (idempotent upsert — same
    dry-run-then-apply pattern used for every other resource Nexus applies).

    Credentials go into a short-lived, owner-only-readable temp file and
    reach kubectl via ``--from-file``, not ``--docker-password=...`` on the
    command line. The latter is the more commonly-seen pattern, but it
    leaves the raw password visible to anything that can read this
    process's argv (``ps aux``, ``/proc/<pid>/cmdline``) for as long as the
    process runs — a temp file deleted immediately after use, readable only
    by this user in the meantime, is a materially smaller exposure window.
    """
    if app.registry is None:
        return
    username, password = resolve_credentials(app)
    config_json = _docker_config_json(app.registry.server, username, password)

    # tempfile.mkstemp creates the file mode 0600 (owner read/write only)
    # from the moment it exists — no window where it's briefly more open.
    fd, tmp_path_str = tempfile.mkstemp(prefix="nexus-dockerconfig-", suffix=".json")
    tmp_path = Path(tmp_path_str)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(config_json)

        result = kubectl.run(
            [
                "create",
                "secret",
                "generic",
                app.registry_secret_name,
                f"--from-file=.dockerconfigjson={tmp_path}",
                "--type=kubernetes.io/dockerconfigjson",
                "-n",
                app.name,
                "--dry-run=client",
                "-o",
                "yaml",
            ]
        )
        kubectl.apply_manifest(result.stdout)
    finally:
        tmp_path.unlink(missing_ok=True)
