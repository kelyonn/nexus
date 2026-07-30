# Amazon EKS

!!! warning "Untested"
    Not yet run against a real EKS cluster — see the
    [cloud quick-starts overview](index.md) for what that means. Corrections
    welcome via a PR or issue.

## Getting a `kubectl` context

```bash
aws eks update-kubeconfig --name <your-cluster-name> --region <region>
kubectl get nodes   # confirm it worked before running anything Nexus-side
```

## Before `nexus deploy`

```bash
nexus doctor
```

Specifically check that this reports:

- `kubectl`/`helm` reachable (should be true if the command above worked)
- your IAM identity has enough RBAC to create namespaces, Deployments,
  Services, and (via the ArgoCD CRDs) Applications — EKS's default
  `aws-auth` mapping is often more restrictive than a local cluster's
  cluster-admin default

## Things likely to need adjustment

- **LoadBalancer → an actual ELB/NLB.** Each app Nexus deploys gets a
  `type: LoadBalancer` Service — on EKS that provisions a real, billed
  Elastic Load Balancer per app. Fine for a handful of apps; know the cost
  implication before deploying many.
- **`platform.repoURL`** needs to be a real GitHub/GitLab HTTPS or SSH URL
  ArgoCD can authenticate against non-interactively (a fine-grained PAT or a
  deploy key) — `git daemon` tricks that work for Minikube's `localhost`
  don't apply once ArgoCD is running inside a cluster it doesn't share a
  host with.
- **Storage class / node sizing** for kube-prometheus-stack's Prometheus and
  Grafana pods — the Helm chart's defaults are conservative but EKS's
  default storage class (`gp2`/`gp3`) should work out of the box.

If you try this against a real EKS cluster, please open an issue (or a PR
to this page) with what actually happened.
