"""``nexus init`` — detect the app's stack and generate nexus.yaml (PRD §7.1).

Output follows the CLI UX flow in PRD §8: a header, the detected/forced stack
and its pre-filled defaults, then prompts for the fields Nexus cannot infer
(image, Git repo URL, branch), ending with a confirmation and next step.
"""

from __future__ import annotations

import re
from pathlib import Path

import typer
from pydantic import ValidationError

from nexus_cli.core import detect, output
from nexus_cli.core.config import AppConfig, NexusConfig, PlatformConfig
from nexus_cli.core.output import NexusError

_NAME_SANITIZE_RE = re.compile(r"[^a-z0-9-]+")

_DISPLAY = {
    "node": ("Node.js", "package.json found"),
    "flask": ("Flask", "app.py + requirements.txt found"),
    "generic": ("Generic", "no recognized stack signals found"),
}


def _default_app_name(directory: Path) -> str:
    """Derive a valid app.name from the directory name (PRD §9 name pattern)."""
    raw = directory.resolve().name.lower()
    name = _NAME_SANITIZE_RE.sub("-", raw).strip("-")
    name = name[:40].rstrip("-")
    return name or "my-app"


def init(
    stack: str | None = typer.Option(
        None,
        "--stack",
        help="Force a stack preset (node, flask, generic) instead of auto-detecting.",
    ),
) -> None:
    """Detect your app's stack and generate a pre-filled nexus.yaml."""
    directory = Path.cwd()
    config_path = directory / "nexus.yaml"

    if config_path.exists():
        overwrite = typer.confirm(f"{config_path.name} already exists. Overwrite?", default=False)
        if not overwrite:
            output.warn("Aborted — nexus.yaml left untouched.")
            raise typer.Exit(code=1)

    output.step("")
    output.step("Nexus Init")
    output.step("-" * 43)

    if stack:
        try:
            preset = detect.preset(stack)
        except NexusError as stack_err:
            output.print_error(stack_err)
            raise typer.Exit(code=1) from stack_err
        signal = "forced via --stack"
    else:
        preset = detect.detect_stack(directory)
        signal = _DISPLAY[preset.name][1]

    display_name = _DISPLAY[preset.name][0]
    output.step(f"Detected stack: {display_name} ({signal})")
    output.step("")

    if preset.name == "generic":
        port = typer.prompt("Enter the port your app listens on", type=int)
        health_path = typer.prompt("Enter your health check path", default="/health")
    else:
        port = preset.port
        health_path = preset.health_path
        output.step("Pre-filled defaults:")
        output.step(f"  port:        {port}")
        output.step(f"  healthPath:  {health_path}")
        if preset.env:
            env_str = ", ".join(f"{e.name}={e.value}" for e in preset.env)
            output.step(f"  env:         {env_str}")
        output.step("")

    image = typer.prompt("Enter your Docker image (e.g. myrepo/app:latest)")
    repo_url = typer.prompt("Enter your Git repo URL")
    branch = typer.prompt("Enter branch", default="main")

    try:
        cfg = NexusConfig(
            app=AppConfig(
                name=_default_app_name(directory),
                image=image,
                port=port,
                healthPath=health_path,
                stack=None if preset.name == "generic" else preset.name,
                env=list(preset.env),
            ),
            platform=PlatformConfig(repoURL=repo_url, branch=branch),
        )
    except ValidationError as exc:
        err = output.from_validation_error(exc, source="your input")
        output.print_error(err)
        raise typer.Exit(code=1) from exc

    config_path.write_text(cfg.to_yaml())

    output.step("")
    output.success(f"Created {config_path.name}")
    output.step("")
    output.step("Next step: run `nexus deploy` to deploy your app.")
