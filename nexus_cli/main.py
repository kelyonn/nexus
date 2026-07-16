"""Nexus CLI entry point.

Defines the Typer application. Subcommands are registered as they are built
(``init`` first — see the implementation plan). For now the app exposes
``--version`` and ``--help`` so the package is installable and runnable.
"""

from __future__ import annotations

import typer

from nexus_cli import __version__

app = typer.Typer(
    name="nexus",
    help="Bring your app. Nexus handles the platform.",
    no_args_is_help=True,
    add_completion=False,
)


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
