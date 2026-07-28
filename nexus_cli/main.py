"""Nexus CLI entry point.

Defines the Typer application and registers each command module. Subcommands
are added below as they are built — see the implementation plan for order.
"""

from __future__ import annotations

import typer

from nexus_cli import __version__
from nexus_cli.commands.deploy import deploy as _deploy_command
from nexus_cli.commands.destroy import destroy as _destroy_command
from nexus_cli.commands.init import init as _init_command
from nexus_cli.commands.logs import logs as _logs_command
from nexus_cli.commands.status import status as _status_command
from nexus_cli.commands.watch import watch as _watch_command

app = typer.Typer(
    name="nexus",
    help="Bring your app. Nexus handles the platform.",
    no_args_is_help=True,
    add_completion=False,
)

app.command(name="init")(_init_command)
app.command(name="deploy")(_deploy_command)
app.command(name="status")(_status_command)
app.command(name="watch")(_watch_command)
app.command(name="logs")(_logs_command)
app.command(name="destroy")(_destroy_command)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"nexus {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        help="Show the Nexus version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """Nexus — deploy any containerized app to Kubernetes with GitOps,
    self-healing, observability, and chaos testing, from one nexus.yaml."""


if __name__ == "__main__":
    app()
