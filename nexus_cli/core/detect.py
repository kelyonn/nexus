"""Stack detection for ``nexus init`` (PRD §7.1, Phase 1 signals only).

Detection looks only at the current working directory (monorepo: run from the
service subdirectory). Django and Go are v2 signals and are intentionally not
detected here (PRD §18).

Note: preset defaults are the *stack's* conventions, not any particular app's
actual config. E.g. the Flask preset defaults to port 5000 / ``/health`` even
though the legacy demo app happens to use 5050 / ``/healthz`` — that demo sets
those explicitly in its own ``nexus.yaml`` (PRD §0).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from nexus_cli.core.config import EnvVar
from nexus_cli.core.output import NexusError


@dataclass(frozen=True)
class StackPreset:
    name: str
    port: int | None = None
    health_path: str | None = None
    env: list[EnvVar] = field(default_factory=list)


_PRESETS: dict[str, StackPreset] = {
    "node": StackPreset(
        name="node",
        port=3000,
        health_path="/health",
        env=[EnvVar(name="NODE_ENV", value="production")],
    ),
    "flask": StackPreset(
        name="flask",
        port=5000,
        health_path="/health",
    ),
    "generic": StackPreset(name="generic"),
}


def preset(name: str) -> StackPreset:
    """Look up a preset by name (used by the ``--stack`` override)."""
    try:
        return _PRESETS[name]
    except KeyError as exc:
        raise NexusError(
            what=f"Unknown stack '{name}'.",
            why="Supported stacks in Phase 1 are: node, flask, generic.",
            fix="Pass one of --stack node, --stack flask, or --stack generic.",
        ) from exc


def detect_stack(directory: str | Path = ".") -> StackPreset:
    """Detect the app's stack from files in ``directory`` (PRD §7.1).

    - ``package.json`` present -> Node.js
    - ``app.py`` and ``requirements.txt`` present -> Flask
    - otherwise -> generic (caller must prompt for port + health path)
    """
    d = Path(directory)
    if (d / "package.json").is_file():
        return _PRESETS["node"]
    if (d / "app.py").is_file() and (d / "requirements.txt").is_file():
        return _PRESETS["flask"]
    return _PRESETS["generic"]
