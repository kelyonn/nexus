#!/usr/bin/env bash
# Nexus installer (PRD §14).
#
# Usage:
#   curl -sSL https://raw.githubusercontent.com/kelyonn/nexus/main/scripts/install.sh | bash
#
# (PRD §14 describes this as eventually hosted at get.nexus.sh — that custom
# domain isn't set up yet, so the real, working URL today is the GitHub raw
# path above.)
#
# What this does, per PRD §14:
#   1. Requires Python 3.10+. If missing, stops with clear instructions
#      rather than trying to install Python itself (fragile across distros,
#      a large support burden — see PRD §15).
#   2. Runs `pip install nexus-gitops` (preferring `pipx` if available, for
#      an isolated install that won't collide with other Python packages).
#   3. Verifies `nexus --version` works.

set -euo pipefail

PACKAGE_NAME="nexus-gitops"
MIN_PYTHON_MAJOR=3
MIN_PYTHON_MINOR=10

info() { printf '\033[1;34m==>\033[0m %s\n' "$1"; }
error() { printf '\033[1;31mError:\033[0m %s\n' "$1" >&2; }

find_python() {
    for candidate in python3 python; do
        if command -v "$candidate" >/dev/null 2>&1; then
            echo "$candidate"
            return 0
        fi
    done
    return 1
}

python_version_ok() {
    "$1" - <<'PYEOF'
import sys
sys.exit(0 if sys.version_info >= (3, 10) else 1)
PYEOF
}

main() {
    info "Looking for Python ${MIN_PYTHON_MAJOR}.${MIN_PYTHON_MINOR}+..."
    PYTHON_BIN="$(find_python)" || {
        error "Python was not found on PATH."
        echo "Install Python ${MIN_PYTHON_MAJOR}.${MIN_PYTHON_MINOR}+ from https://www.python.org/downloads/ and re-run this script." >&2
        exit 1
    }

    if ! python_version_ok "$PYTHON_BIN"; then
        found_version="$("$PYTHON_BIN" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"
        error "Found Python ${found_version}, but Nexus needs ${MIN_PYTHON_MAJOR}.${MIN_PYTHON_MINOR}+."
        echo "Install a newer Python from https://www.python.org/downloads/ and re-run this script." >&2
        exit 1
    fi
    info "Python OK ($("$PYTHON_BIN" --version 2>&1))."

    if command -v pipx >/dev/null 2>&1; then
        info "Installing ${PACKAGE_NAME} with pipx (isolated environment)..."
        pipx install "$PACKAGE_NAME"
    else
        info "pipx not found — installing ${PACKAGE_NAME} with pip --user instead."
        info "(Tip: install pipx for isolated CLI installs: https://pipx.pypa.io/stable/installation/)"
        "$PYTHON_BIN" -m pip install --user "$PACKAGE_NAME"
    fi

    info "Verifying installation..."
    if command -v nexus >/dev/null 2>&1; then
        nexus --version
        info "Nexus installed. Run 'nexus init' to get started."
    else
        error "'nexus' isn't on PATH yet."
        echo "It was installed, but its directory may not be on PATH in this shell." >&2
        echo "Open a new terminal, or add the install location to PATH, then run 'nexus --version'." >&2
        exit 1
    fi
}

main "$@"
