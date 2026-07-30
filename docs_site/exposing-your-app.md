# Exposing your app

Nexus generates a `Service` for your app (`service.yaml.j2`) but no
`Ingress`, no TLS, and no domain name — that's a deliberate scope boundary,
not an oversight. Here's why, and the three ways to actually reach your app
depending on what you need.

## Why there's no Ingress template

An Ingress needs an Ingress controller already running in the cluster
(nginx-ingress, Traefik, a cloud provider's own), which one is installed
varies by environment, and TLS on top of that needs cert-manager plus a
real DNS name pointing at the cluster — none of which Nexus can assume or
safely install unprompted the way it does ArgoCD/Prometheus/Chaos Mesh
(those are opinionated, single-choice installs; "which Ingress controller"
is not). Getting this wrong would mean either forcing one specific
controller on everyone, or building a much bigger abstraction over several
incompatible ones. Neither fits "one YAML file, no dedicated platform team."

## Option 1 — `kubectl port-forward` (the default, works everywhere)

What `nexus deploy` itself prints on success, and what `app.serviceType`
defaults to (`ClusterIP`) is built for:

```bash
kubectl -n <app-name> port-forward svc/<app-name> 18080:80
# → http://127.0.0.1:18080
```

Works identically on Minikube, Kind, and any real cloud cluster — no cloud
resources provisioned, nothing billed. The right choice for local
development and demos. Not suitable for anything another person needs to
reach without running `kubectl` themselves.

## Option 2 — `NodePort` or `LoadBalancer` (`app.serviceType`)

```yaml
app:
  serviceType: LoadBalancer # or NodePort
```

`LoadBalancer` provisions a real, billed cloud load balancer per app on a
real cluster (see [Cloud quick-starts](cloud/index.md)) — or needs `minikube
tunnel` locally. `NodePort` exposes the Service on a static port on every
node's own IP, no cloud resource provisioned, but you're reaching a raw IP
and port, not a domain name.

## Option 3 — bring your own Ingress + cert-manager

For a real domain name and TLS, install an Ingress controller and
cert-manager the same way you'd install any other cluster-wide component
(Helm, same as `nexus deploy` does for ArgoCD/Prometheus/Chaos Mesh — just
not automated by Nexus), then point an `Ingress` at the `Service` Nexus
already created. It already has a stable name (`<app-name>`) and a named
`http` port — nothing app-specific to look up:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: <app-name>
  namespace: <app-name>
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod # if using cert-manager
spec:
  ingressClassName: nginx # whatever controller you installed
  tls:
    - hosts: ["app.example.com"]
      secretName: <app-name>-tls
  rules:
    - host: app.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: <app-name>
                port:
                  name: http
```

Apply it with `kubectl apply -f` directly, or commit it into the `k8s/`
directory `nexus deploy` already manages alongside the generated manifests
— either way, Nexus doesn't need to know about it; it's just another
resource in the same namespace pointing at a Service that already exists.

**Not yet available as a schema field or template.** If you want autoscaling
too, see [FUTURE-SCOPE.md](https://github.com/kelyonn/nexus/blob/main/FUTURE-SCOPE.md) —
a similar "this needs a real design decision, not a quick add" case.
