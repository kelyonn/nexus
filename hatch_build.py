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
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class DashboardFrontendBuildHook(BuildHookInterface):  # type: ignore[misc]
    def initialize(self, version: str, build_data: dict[str, object]) -> None:
        if os.environ.get("NEXUS_SKIP_DASHBOARD_BUILD"):
            self.app.display_info("NEXUS_SKIP_DASHBOARD_BUILD set — skipping frontend build.")
            return

        frontend_dir = Path(self.root) / "dashboard" / "frontend"
        out_dir = frontend_dir / "out"
        if (out_dir / "index.html").is_file():
            self.app.display_info(f"{out_dir} already built — skipping.")
            return

        if shutil.which("npm") is None:
            self.app.display_warning(
                "npm not found — building without the dashboard frontend bundled. "
                "`nexus dashboard` will report it's missing at runtime (with a fix). "
                "Install Node.js and rebuild to include it."
            )
            return

        env = {**os.environ, "NEXUS_STATIC_EXPORT": "1"}
        self.app.display_info(f"Building dashboard frontend static export in {frontend_dir}...")
        subprocess.run(["npm", "ci"], cwd=frontend_dir, env=env, check=True)
        subprocess.run(["npm", "run", "build"], cwd=frontend_dir, env=env, check=True)
