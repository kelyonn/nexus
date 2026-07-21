# Installation

## Installing Nexus (users)

> 🚧 **Not yet published.** Nexus has not shipped its first release. When
> Phase 1 lands, installation will be:
>
> ```bash
> pip install nexus-platform          # PyPI (P0)
> curl -sSL https://get.nexus.sh | bash   # installer script (P0)
> brew tap kelyonnnn17/nexus && brew install nexus   # Homebrew (P1)
> ```

Until then, this document covers **contributor setup** — the environment for
building Nexus itself.

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

The CLI wraps `kubectl` and `helm` and needs a local cluster to test against.

**macOS (Homebrew):**

```bash
brew install --cask docker
brew install minikube kubectl helm git
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

### 4) Quality gates

Run before every commit (CI will enforce these):

```bash
ruff check .
mypy nexus_cli
pytest
```

## Platform components (ArgoCD, monitoring, Chaos Mesh)

`nexus deploy` will install these automatically via Helm. For manual
experimentation or debugging, the hand-install commands are preserved in
[legacy/INSTALLATION.md](legacy/INSTALLATION.md) §5 — they are exactly what the
CLI automates.
