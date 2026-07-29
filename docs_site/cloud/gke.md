# Google GKE

!!! warning "Untested"
    Not yet run against a real GKE cluster — see the
    [cloud quick-starts overview](index.md) for what that means. Corrections
    welcome via a PR or issue.

## Getting a `kubectl` context

```bash
gcloud container clusters get-credentials <cluster-name> --zone <zone> --project <project>
kubectl get nodes   # confirm it worked before running anything Nexus-side
```

## Before `nexus deploy`

```bash
nexus doctor
```

Specifically check RBAC: your GCP identity needs to be bound (via
`kubectl create clusterrolebinding` or GKE's IAM-to-RBAC mapping) with
enough permission to create namespaces, Deployments, Services, and — once
ArgoCD's CRDs are installed — Applications. GKE's default is more
restrictive than a local cluster's cluster-admin default, especially on
Autopilot clusters (which also restrict some workload types Nexus doesn't
currently account for — untested).

## Things likely to need adjustment

- **LoadBalancer → an actual GCP Load Balancer.** Each app Nexus deploys
  gets `type: LoadBalancer` — real, billed, one per app.
- **`platform.repoURL`** needs a real reachable GitHub/GitLab URL — same
  reasoning as [EKS](eks.md#things-likely-to-need-adjustment).
- **Autopilot vs Standard.** Standard GKE clusters should behave like any
  other Kubernetes cluster from Nexus's point of view. Autopilot enforces
  additional pod-level restrictions (resource requests/limits required on
  every container, some security-context defaults) that haven't been
  checked against what Nexus's templates currently set.

If you try this against a real GKE cluster, please open an issue (or a PR
to this page) with what actually happened.
