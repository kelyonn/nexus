# Azure AKS

!!! warning "Untested"
    Not yet run against a real AKS cluster — see the
    [cloud quick-starts overview](index.md) for what that means. Corrections
    welcome via a PR or issue.

## Getting a `kubectl` context

```bash
az aks get-credentials --resource-group <resource-group> --name <cluster-name>
kubectl get nodes   # confirm it worked before running anything Nexus-side
```

## Before `nexus deploy`

```bash
nexus doctor
```

Specifically check RBAC: if the cluster has Azure AD integration enabled,
your identity needs an appropriate role binding (`Azure Kubernetes Service
RBAC Writer`/`Admin`, or an equivalent Kubernetes-native `RoleBinding`) with
enough permission to create namespaces, Deployments, Services, and — once
ArgoCD's CRDs are installed — Applications.

## Things likely to need adjustment

- **LoadBalancer → an actual Azure Load Balancer.** Each app Nexus deploys
  gets `type: LoadBalancer` — real, billed, one per app.
- **`platform.repoURL`** needs a real reachable GitHub/GitLab/Azure Repos
  URL — same reasoning as [EKS](eks.md#things-likely-to-need-adjustment).
- **Default storage class** — AKS's default (`managed-csi` on newer
  clusters, `default`/`managed-premium` on older ones) should work for
  kube-prometheus-stack's Prometheus/Grafana persistent volumes, but hasn't
  been checked.

If you try this against a real AKS cluster, please open an issue (or a PR
to this page) with what actually happened.
