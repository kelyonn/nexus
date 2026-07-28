# Installation

## Installing Nexus (users)

> 🚧 **Not yet published to PyPI.** The commands below are the real, tested
> install path — the installer script and `pyproject.toml` packaging are both
> built and verified against a locally-built wheel — but `pip install
> nexus-gitops` won't resolve anything until the first `v0.1.0` tag is
> actually published (see [.github/workflows/release.yml](.github/workflows/release.yml)).
> Until then, use [Contributor setup](#contributor-setup) below to run from
> source.

Once published:

```bash
pip install nexus-gitops
# or, the installer script (checks Python 3.10+, prefers pipx, verifies the install):
curl -sSL https://raw.githubusercontent.com/kelyonn/nexus/main/scripts/install.sh | bash
```

(PRD §14 also names Homebrew as a later, P1 distribution channel — not built yet.)

This document covers **contributor setup** — the environment for building
Nexus itself.

## Contributor setup

### 1) Python toolchain

Nexus requires **Python 3.10+**.

```bash
python3 --version                   # must be >= 3.10
cd nexus                            # repo root
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
```

Install the package editable with dev extras:

```bash
pip install -e ".[dev]"             # typer, jinja2, pyyaml, kubernetes,
                                    # pytest, pytest-cov, ruff, mypy
```

### 2) Cluster tooling (for integration tests / manual verification)

The CLI wraps `kubectl` and `helm` and needs a local cluster to test against —
either Minikube or [Kind](https://kind.sigs.k8s.io/) (CI uses Kind; both are
exercised the same way locally).

**macOS (Homebrew):**

```bash
brew install --cask docker
brew install minikube kind kubectl helm git
```

**Windows (winget):**

```powershell
winget install Docker.DockerDesktop Kubernetes.minikube Kubernetes.kubectl Helm.Helm Git.Git
```

**Linux:** install Docker from your distro docs, then kubectl/minikube/helm per
their official install scripts (full commands preserved in
[legacy/INSTALLATION.md](legacy/INSTALLATION.md) §2).

**Verify:**

```bash
docker version && minikube version && kubectl version --client && helm version
```

### 3) Start a local cluster

```bash
minikube start --driver=docker
kubectl get nodes                   # expect one Ready node
```

If the API becomes unreachable after a reboot (`EOF` / `TLS handshake
timeout`): `minikube update-context && minikube start --driver=docker`.

Or with Kind:

```bash
kind create cluster --name nexus-dev
kubectl get nodes                   # expect one Ready node
```

### 4) Quality gates

Run before every commit (CI enforces these — [.github/workflows/ci.yml](.github/workflows/ci.yml)):

```bash
ruff check .
mypy nexus_cli
pytest                              # fast unit suite only, ~1s, no cluster needed
```

### 5) Integration tests (needs a real cluster — start one per step 3 first)

```bash
pytest tests/integration -m "not chaos"    # deploy/status/destroy, idempotency, preflight failures
pytest tests/integration/test_chaos.py -m chaos   # separate: installs Chaos Mesh, slower, can be flaky on Kind
```

Not part of the default `pytest` run (see `tool.pytest.ini_options` in
`pyproject.toml`) — these take minutes, not seconds, and need a live cluster.

## Platform components (ArgoCD, monitoring, Chaos Mesh)

`nexus deploy` will install these automatically via Helm. For manual
experimentation or debugging, the hand-install commands are preserved in
[legacy/INSTALLATION.md](legacy/INSTALLATION.md) §5 — they are exactly what the
CLI automates.
