# Nexus: Self-Healing GitOps Platform

Nexus is an open-source learning project that shows how to run a Kubernetes app with a full GitOps workflow: deploy from Git, auto-heal drift, observe runtime metrics, and run controlled chaos tests.

## Quick Command Map

Use this section when you want a fast command without reading full docs.

| If you want to... | Run this command |
| --- | --- |
| Start local cluster | `minikube start --driver=docker` |
| Verify cluster is healthy | `kubectl get nodes` |
| See GitOps app states | `kubectl get application -n argocd -o wide` |
| Watch app rollout in real time | `kubectl get pods -n nexus -w` |
| Open Nexus app locally | `kubectl -n nexus port-forward svc/nexus-service 18080:80` |
| Open ArgoCD UI | `minikube service argocd-server -n argocd` |
| Get ArgoCD admin password (macOS/Linux) | `kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 --decode; echo` |
| Get ArgoCD admin password (PowerShell) | `$b64 = kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}"; [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($b64))` |
| Open Grafana locally | `kubectl -n monitoring port-forward svc/kube-prom-stack-grafana 3000:80` |
| Trigger self-healing manually | `kubectl delete pod -n nexus -l app=nexus-app` |
| Test drift correction | `kubectl scale deployment nexus-app -n nexus --replicas=1` |
| Check chaos experiments | `kubectl get schedule,podchaos -n chaos-mesh` |
| Recover from EOF / TLS timeout | `minikube update-context; minikube start --driver=docker` |

## Features

- **GitOps deployment with ArgoCD**
  - Automatic sync from Git to cluster
  - Automatic drift correction (`selfHeal`) and cleanup (`prune`)
- **Kubernetes app operations**
  - Flask app deployed as a replicated `Deployment`
  - Service exposure through `Service` + local port-forward
- **Self-healing behavior**
  - Pod replacement on failure/deletion
  - Desired state restoration after manual drift
- **Observability stack**
  - Prometheus Operator-based monitoring
  - Grafana datasource + dashboards from repo manifests
- **Chaos engineering integration**
  - Chaos Mesh `PodChaos` + schedule to simulate disruptions
  - Resilience validation under repeated pod terminations

## How it works (high level)

1. You push manifest changes to Git.
2. ArgoCD watches your branch and syncs changes into Minikube.
3. Kubernetes applies rollout and keeps desired replicas running.
4. Prometheus/Grafana expose health and performance signals.
5. Chaos Mesh injects failures; Kubernetes + ArgoCD recover state.

## Architecture

- **Application**: Flask (`app/`)
- **Container image**: `kelyonnnn17/nexus-app:v1` (default)
- **Cluster**: Minikube
- **GitOps controller**: ArgoCD
- **Monitoring**: kube-prometheus-stack + Grafana
- **Chaos**: Chaos Mesh

ArgoCD application mapping:

- `nexus-app` -> `k8s/`
- `nexus-monitoring` -> `monitoring/`
- `nexus-chaos` -> `chaos/`

## Repository layout

```text
app/                          Flask source + Dockerfile
k8s/                          Core app manifests (namespace, deploy, service)
monitoring/                   PrometheusRule, Grafana datasource, dashboards
chaos/                        PodChaos and schedule manifests
argocd/                       ArgoCD Applications (monitoring + chaos)
application.yaml              ArgoCD Application (core app)
INSTALLATION.md               Full setup/install guide
```

## Requirements

You need these tools installed:

- Docker Desktop / Docker Engine
- Minikube
- kubectl
- Helm (v3+)
- Git

For complete install commands by OS, see [INSTALLATION.md](INSTALLATION.md).

## Quick start

### 1) Start cluster

```bash
minikube start --driver=docker
kubectl get nodes
```

### 2) Install dependencies

Follow [INSTALLATION.md](INSTALLATION.md) to install:

- ArgoCD
- kube-prometheus-stack
- Chaos Mesh

### 3) Configure your repo + branch

Update these manifests before applying:

- `application.yaml`
- `argocd/application-monitoring.yaml`
- `argocd/application-chaos.yaml`

Set:

- `spec.source.repoURL` = your GitHub repo URL
- `spec.source.targetRevision` = your branch (for example `main`)

### 4) Apply GitOps applications

```powershell
kubectl apply -f application.yaml
kubectl apply -f argocd/application-monitoring.yaml
kubectl apply -f argocd/application-chaos.yaml
kubectl get application -n argocd -o wide
```

Expected: all applications become `Synced` and `Healthy/Progressing`.

## Day-to-day usage

### Make a release change

1. Edit manifest config (example: `k8s/deployment.yaml`).
2. Commit and push to tracked branch.
3. Verify rollout:

```powershell
kubectl get application -n argocd -w
kubectl get pods -n nexus -w
```

### Access UIs/services

- **App**

```powershell
kubectl -n nexus port-forward svc/nexus-service 18080:80
```

Open `http://127.0.0.1:18080`

- **ArgoCD**

```powershell
minikube service argocd-server -n argocd
```

Initial login:

- Username: `admin`
- Password (macOS/Linux):

```bash
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 --decode; echo
```

- Password (PowerShell):

```powershell
$b64 = kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}"
[System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($b64))
```

- **Grafana**

```powershell
kubectl -n monitoring port-forward svc/kube-prom-stack-grafana 3000:80
```

Open `http://127.0.0.1:3000`

## Self-healing test checklist

Use this sequence to verify resilience:

1. **Pod delete recovery**

```powershell
kubectl delete pod -n nexus -l app=nexus-app
kubectl get pods -n nexus -w
```

Expected: deleted pods are recreated.

2. **Drift correction**

```powershell
kubectl scale deployment nexus-app -n nexus --replicas=1
kubectl get deployment nexus-app -n nexus -w
```

Expected: ArgoCD restores desired replica count from Git.

3. **Chaos resilience**

```powershell
kubectl get schedule,podchaos -n chaos-mesh
kubectl get pods -n nexus -w
```

Expected: periodic pod terminations and automatic recovery.

## Troubleshooting

- **`EOF` / `TLS handshake timeout` / API unreachable**
  - `minikube update-context`
  - `minikube start --driver=docker`
  - Retry command
- **Argo app stuck `OutOfSync` with missing CRDs**
  - Ensure monitoring + chaos Helm dependencies are installed first
- **Windows: `base64` command not found**
  - Use PowerShell decode snippet in this README
- **`minikube service` unstable on Windows Docker driver**
  - Use `kubectl port-forward` for reliable access

## Security note

This project is for local/lab usage by default. Before production usage, harden:

- ArgoCD authentication and RBAC
- Secrets management (do not store secrets in Git)
- Image provenance and vulnerability scanning
- Network policies and TLS settings

## Contributing

PRs are welcome.

Please include:

- What changed
- Why it changed
- How you tested it