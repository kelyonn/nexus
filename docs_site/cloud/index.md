# Cloud quick-starts

!!! warning "Untested against real cloud clusters"
    Everything else on this site — the golden path, the troubleshooting
    entries, the architecture notes — has been live-verified against a real
    cluster (Minikube or Kind). The pages in this section have **not**. They
    describe how Nexus's existing preflight checks and Helm-chart installs
    *should* behave on a managed Kubernetes service, based on how those
    components normally work, but nothing here has been run against a real
    EKS, GKE, or AKS cluster. Treat it as a starting point, not a verified
    guide, and please open an issue with corrections if you try it.

Nexus itself doesn't know or care which Kubernetes distribution it's
talking to — `nexus deploy` only needs a reachable cluster with a working
`kubectl` context (`kubectl get nodes` succeeding is `nexus doctor`'s first
check). The differences below are all about how you *get* that reachable
context, and what changes about the components Nexus installs into it
(ArgoCD, kube-prometheus-stack, Chaos Mesh) once it's a real, internet-
reachable cluster rather than a local one.

- [Amazon EKS](eks.md)
- [Google GKE](gke.md)
- [Azure AKS](aks.md)

## What's different from Minikube, in general

- **`platform.repoURL` must be a real remote your cluster can reach.**
  Minikube's `localhost` trick (a `git daemon` reachable via
  `host.minikube.internal`) doesn't apply — ArgoCD needs to reach an actual
  GitHub/GitLab/etc. URL. Use HTTPS with a token, or SSH with a deploy key,
  either way something ArgoCD can authenticate with non-interactively.
- **The Service defaults to `ClusterIP`** (`app.serviceType`), reachable via
  the `kubectl port-forward` command `nexus deploy` prints on success — that
  works the same way everywhere, Minikube or real cloud. Set
  `app.serviceType: LoadBalancer` if you actually want one: on Minikube that
  additionally needs `minikube tunnel`; on a real cloud cluster it
  provisions a real, billed load balancer per app — know that before setting
  it on more than a couple of apps. `NodePort` is also available.
- **RBAC is stricter by default.** `nexus doctor` checks for the RBAC
  permissions Nexus needs (creating namespaces, Deployments, Services,
  ArgoCD Applications, etc.) — run it after setting your `kubectl` context
  to catch a permissions gap before `nexus deploy` does.
- **Ingress isn't something Nexus sets up.** There's no Ingress template —
  see [Exposing your app](../exposing-your-app.md) for the actual options
  (port-forward, NodePort, or bringing your own Ingress + cert-manager) and
  why that's a deliberate scope boundary, not an oversight.
