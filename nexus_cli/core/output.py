"""Terminal output helpers and the Nexus error type.

Every user-facing error must state **what** went wrong, **why** (if known), and a
recommended **fix** (PRD §12). ``NexusError`` carries those three parts and
``print_error`` renders them in the style of the CLI UX flows (PRD §8).
"""

from __future__ import annotations

import typer
from pydantic import ValidationError

# Nexus's terminal palette — muted, not the raw ANSI 8. Every colored helper
# below draws from this set so `nexus` looks like one tool across commands.
BLUE = (110, 156, 204)
GREEN = (127, 184, 148)
AMBER = (207, 159, 104)
RED = (201, 123, 123)
DIM = (124, 133, 145)
BRIGHT = (232, 236, 241)

BANNER = r"""███╗   ██╗███████╗██╗  ██╗██╗   ██╗███████╗
████╗  ██║██╔════╝╚██╗██╔╝██║   ██║██╔════╝
██╔██╗ ██║█████╗   ╚███╔╝ ██║   ██║███████╗
██║╚██╗██║██╔══╝   ██╔██╗ ██║   ██║╚════██║
██║ ╚████║███████╗██╔╝ ██╗╚██████╔╝███████║
╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝"""


class NexusError(Exception):
    """A user-facing error with what / why / fix parts (PRD §12).

    ``what`` is required; ``why`` and ``fix`` are optional but strongly
    encouraged. The string form is the rendered, human-readable message.
    """

    def __init__(self, what: str, why: str | None = None, fix: str | None = None) -> None:
        self.what = what
        self.why = why
        self.fix = fix
        super().__init__(format_error(self))


def format_error(err: NexusError) -> str:
    """Render a NexusError as a what / why / fix block."""
    lines = [err.what]
    if err.why:
        lines += ["", err.why]
    if err.fix:
        lines += ["", err.fix]
    return "\n".join(lines)


def print_error(err: NexusError) -> None:
    """Print a NexusError to stderr in red, set off by a blank line above it."""
    typer.echo("", err=True)
    typer.secho(format_error(err), fg=RED, err=True)


def from_validation_error(exc: ValidationError, *, source: str = "nexus.yaml") -> NexusError:
    """Translate a Pydantic ``ValidationError`` into a single NexusError.

    Keeps the friendly what/why/fix UX on top of Pydantic's raw errors: each
    failing field is reported as ``app.port: <message> (got: <value>)``.
    """
    problems: list[str] = []
    for e in exc.errors():
        loc = ".".join(str(part) for part in e["loc"]) or "(root)"
        msg = e.get("msg", "invalid value")
        given = e.get("input", None)
        problems.append(f"  {loc}: {msg} (got: {given!r})")
    why = f"{len(problems)} problem(s) found:\n" + "\n".join(problems)
    return NexusError(
        what=f"Invalid {source}.",
        why=why,
        fix=f"Fix the field(s) above in {source} and re-run. See the config schema for the rules.",
    )


def success(message: str) -> None:
    typer.secho(f"✓ {message}", fg=GREEN)


def step(message: str) -> None:
    typer.echo(message)


def warn(message: str) -> None:
    typer.secho(f"! {message}", fg=AMBER)


def check(passed: bool, detail: str) -> None:
    """One line of a preflight/diagnostic checklist: ✓ in green, ✗ in red."""
    glyph, color = ("✓", GREEN) if passed else ("✗", RED)
    typer.secho(f"{glyph} {detail}", fg=color)


def header(title: str) -> None:
    """The banner every command opens with: a bold title over a dim rule."""
    typer.echo("")
    typer.secho(title, fg=BRIGHT, bold=True)
    typer.secho("-" * 43, fg=DIM)


def info(message: str) -> None:
    """A step that's actively happening — numbered progress, "waiting for X"."""
    typer.secho(message, fg=BLUE)


def banner() -> None:
    """The NEXUS wordmark — shown once, at `nexus init`'s first-run moment."""
    typer.secho(BANNER, fg=BLUE)
    typer.echo("")
