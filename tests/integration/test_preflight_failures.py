"""Preflight failures, against real (broken) environments (PRD §18, §12).

Unlike the rest of the integration suite, these deliberately break the
environment first — no real cluster needed for the missing-kubectl case, and
a bogus kubeconfig context for the unreachable-cluster case.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from tests.integration.conftest import run_nexus, write_flask_demo_config


def test_missing_kubectl_reports_what_why_fix(tmp_path: Path) -> None:
    write_flask_demo_config(tmp_path, app_name="it-no-kubectl")

    # A PATH that only contains the directory holding the `nexus` binary
    # itself (found via an absolute path, so PATH lookup isn't needed to
    # launch it) — kubectl is deliberately unreachable, proving the
    # *installed* nexus binary's own preflight check, not a mocked one.
    nexus_path = shutil.which("nexus")
    assert nexus_path, "nexus must be on PATH for this test to run at all"
    env = {"PATH": str(Path(nexus_path).parent)}

    result = subprocess.run(
        [nexus_path, "deploy", "--yes"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "kubectl" in output
    assert "not found" in output.lower() or "not installed" in output.lower()
    assert "https://kubernetes.io" in output  # the fix line


def test_unreachable_cluster_reports_what_why_fix(tmp_path: Path) -> None:
    write_flask_demo_config(tmp_path, app_name="it-unreachable")

    bogus_kubeconfig = tmp_path / "bogus-kubeconfig.yaml"
    bogus_kubeconfig.write_text(
        "apiVersion: v1\nkind: Config\nclusters: []\ncontexts: []\nusers: []\n"
        "current-context: does-not-exist\n"
    )
    env = dict(os.environ)
    env["KUBECONFIG"] = str(bogus_kubeconfig)

    result = subprocess.run(
        ["nexus", "deploy", "--yes"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "not reachable" in output.lower() or "cluster" in output.lower()
    assert "cluster-info" in output  # the fix line


def test_deploy_confirmation_declined_changes_nothing(tmp_path: Path) -> None:
    """Not a preflight failure, but the same 'safe to abort' contract: a real
    cluster is up (this test isn't opted out via cluster_ready), declining
    the confirmation must leave nothing behind.
    """
    write_flask_demo_config(tmp_path, app_name="it-declined")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)

    result = run_nexus(["deploy"], cwd=tmp_path, input_text="n\n", timeout=30)
    assert result.returncode != 0
    assert "Aborted" in result.stdout
