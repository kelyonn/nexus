# Installation Guide

This guide covers everything required to run Nexus locally with Minikube.

## 1) Required tools

- Docker Desktop (or Docker Engine)
- Minikube
- kubectl
- Helm (v3+)
- Git

## 2) Install tools

### Windows (recommended with winget)

```powershell
winget install Docker.DockerDesktop
winget install Kubernetes.minikube
winget install Kubernetes.kubectl
winget install Helm.Helm
winget install Git.Git
```

### macOS (Homebrew)

```bash
brew install --cask docker
brew install minikube kubectl helm git
```

### Linux (example)

Install Docker from your distro docs, then:

```bash
# kubectl
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl

# minikube
curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64
sudo install minikube-linux-amd64 /usr/local/bin/minikube

# helm
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
```

## 3) Verify installations

```bash
docker version
minikube version
kubectl version --client
helm version
git --version
```

## 4) Start Minikube

```bash
minikube start --driver=docker
kubectl get nodes
```

If Kubernetes commands fail after a restart:

```bash
minikube update-context
minikube start --driver=docker
```

## 5) Install platform dependencies

### ArgoCD

```bash
kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml --server-side --force-conflicts
kubectl get pods -n argocd
```

### Monitoring stack (Prometheus Operator + Grafana)

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
helm upgrade --install kube-prom-stack prometheus-community/kube-prometheus-stack -n monitoring --create-namespace
```

Verify CRDs:

- Windows PowerShell:

```powershell
kubectl get crd | findstr monitoring.coreos.com
```

- macOS/Linux:

```bash
kubectl get crd | grep monitoring.coreos.com
```

### Chaos Mesh

```bash
helm repo add chaos-mesh https://charts.chaos-mesh.org
helm repo update
helm upgrade --install chaos-mesh chaos-mesh/chaos-mesh -n chaos-mesh --create-namespace --set chaosDaemon.runtime=containerd --set chaosDaemon.socketPath=/run/containerd/containerd.sock
```

Verify CRDs:

- Windows PowerShell:

```powershell
kubectl get crd | findstr chaos-mesh.org
```

- macOS/Linux:

```bash
kubectl get crd | grep chaos-mesh.org
```

## 6) Configure GitOps source

Update these files with your repo and branch:

- `application.yaml`
- `argocd/application-monitoring.yaml`
- `argocd/application-chaos.yaml`

Set:

- `spec.source.repoURL` to your GitHub repo URL
- `spec.source.targetRevision` to your branch (for example `main`)

## 7) Apply ArgoCD Applications

```bash
kubectl apply -f application.yaml
kubectl apply -f argocd/application-monitoring.yaml
kubectl apply -f argocd/application-chaos.yaml
kubectl get application -n argocd -o wide
```

## 8) Access services

### Nexus app

```bash
kubectl -n nexus port-forward svc/nexus-service 18080:80
```

Open `http://127.0.0.1:18080`

### ArgoCD UI

```bash
minikube service argocd-server -n argocd
```

Username: `admin`

Password (Windows PowerShell):

```powershell
$b64 = kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}"
[System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($b64))
```

Password (macOS/Linux):

```bash
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 --decode; echo
```

### Grafana UI

```bash
kubectl -n monitoring port-forward svc/kube-prom-stack-grafana 3000:80
```

Open `http://127.0.0.1:3000`

## 9) Quick health checks

```bash
kubectl get application -n argocd -o wide
kubectl get pods -n nexus
kubectl get pods -n monitoring
kubectl get pods -n chaos-mesh
```

## 10) Common issues

- `Unable to connect to the server: EOF` or `TLS handshake timeout`
  - `minikube update-context`
  - `minikube start --driver=docker`
  - Retry command
- Argo app stuck `OutOfSync` with missing CRDs
  - Ensure monitoring and chaos Helm installs completed
- `minikube service` not reachable on Windows
  - Prefer `kubectl port-forward`
