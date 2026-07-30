"""Hatchling build hook: builds the dashboard frontend's static export before
packaging (PRD §13 — pip-installable dashboard, no Node runtime for the
end user). See dashboard/frontend/next.config.ts and
nexus_cli/core/dashboard.py's module docstring for the rest of this design.

Node/npm are a *maintainer*-time requirement (building a release wheel),
never a user one — this degrades gracefully rather than failing the whole
build if npm isn't available, matching this project's existing philosophy
of optional pieces failing informatively instead of blocking everything
else (e.g. the `dashboard` extra itself, PRD §12).

Skip entirely with NEXUS_SKIP_DASHBOARD_BUILD=1 — useful for a Python-only
contributor doing an editable install (`pip install -e .`) who doesn't have
Node and isn't touching the dashboard.

Every "skip the real build" path below must still leave
`dashboard/frontend/out/` present as *some* directory (even empty) before
returning — see `_ensure_out_dir_exists`'s docstring for why this isn't
optional: hatchling's own packaging step, not this hook, raises
`FileNotFoundError` otherwise, for every build type this hook handles.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class DashboardFrontendBuildHook(BuildHookInterface):  # type: ignore[misc]
    def initialize(self, version: str, build_data: dict[str, object]) -> None:
        frontend_dir = Path(self.root) / "dashboard" / "frontend"
        out_dir = frontend_dir / "out"

        if version == "editable":
            # `pip install -e .` routes through this same hook (hatchling's
            # wheel builder dispatches both "standard" and "editable" through
            # build hooks), but an editable install only ever needs
            # `nexus_cli` live-linked — the dashboard frontend build_data this
            # hook sets isn't consulted for `-e .` at all. Running `npm ci` +
            # `npm run build` here was previously unconditional, so a
            # Python-only contributor with Node installed paid a full
            # frontend build (or a hard failure on a flaky npm registry, see
            # below) just to get an editable install of the CLI.
            self.app.display_info("Editable install — skipping frontend build.")
            _ensure_out_dir_exists(out_dir)
            return
        if os.environ.get("NEXUS_SKIP_DASHBOARD_BUILD"):
            self.app.display_info("NEXUS_SKIP_DASHBOARD_BUILD set — skipping frontend build.")
            _ensure_out_dir_exists(out_dir)
            return

        if (out_dir / "index.html").is_file():
            self.app.display_info(f"{out_dir} already built — skipping.")
            return

        if shutil.which("npm") is None:
            self.app.display_warning(
                "npm not found — building without the dashboard frontend bundled. "
                "`nexus dashboard` will report it's missing at runtime (with a fix). "
                "Install Node.js and rebuild to include it."
            )
            _ensure_out_dir_exists(out_dir)
            return

        env = {**os.environ, "NEXUS_STATIC_EXPORT": "1"}
        self.app.display_info(f"Building dashboard frontend static export in {frontend_dir}...")
        # Not check=True: this module's own docstring promises "degrades
        # gracefully rather than failing the whole build" for exactly this
        # step, matching the `npm not found` branch above — but a raised
        # CalledProcessError from check=True would abort the whole `pip
        # install` instead. A flaky npm registry response (or any other
        # transient `npm ci`/`npm run build` failure) now produces the same
        # "built without the dashboard frontend, here's how to get it"
        # warning as npm being absent entirely, rather than a hard failure.
        for cmd in (["npm", "ci"], ["npm", "run", "build"]):
            result = subprocess.run(cmd, cwd=frontend_dir, env=env, capture_output=True, text=True)
            if result.returncode != 0:
                self.app.display_warning(
                    f"`{' '.join(cmd)}` failed — building without the dashboard frontend "
                    "bundled. `nexus dashboard` will report it's missing at runtime (with a "
                    f"fix). Output:\n{result.stdout}\n{result.stderr}"
                )
                _ensure_out_dir_exists(out_dir)
                return


def _ensure_out_dir_exists(out_dir: Path) -> None:
    """Every path that skips the real frontend build must still leave
    ``out_dir`` present as *some* directory, even empty.

    ``pyproject.toml``'s ``force-include`` maps ``dashboard/frontend/out`` ->
    a location in the wheel — and hatchling's own packaging step (not this
    hook; it runs afterward, unconditionally) raises ``FileNotFoundError``
    if a force-include source is neither a file nor a directory, for
    *every* build type this hook handles (standard and editable alike;
    confirmed by reading hatchling's own ``recurse_forced_files``, which has
    no "silently skip a missing source" branch). An empty directory
    contributes zero files to the wheel and is exactly what
    ``core/dashboard.py``'s own runtime check (looks for
    ``out/index.html`` specifically) needs to keep reporting "frontend
    isn't built" accurately — this must never create a placeholder
    ``index.html``, only the directory itself.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
