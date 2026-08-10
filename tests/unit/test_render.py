"""The golden test: rendered templates reproduce the legacy manifests (PRD §0).

Design notes / deliberate deviations from a literal byte-for-byte comparison:

1. **Namespace vs. resource name.** The legacy manifests use two different
   strings: the app namespace is ``nexus`` (namespace.yaml, and the
   ``namespace:`` field in deployment.yaml/service.yaml), while the
   Deployment/Service *names* and ``app`` labels are ``nexus-app``. PRD §9
   states a single ``app.name`` field drives *both* the namespace and the
   resource names — so the new schema necessarily unifies these under one
   value. This test therefore compares each field against what the schema
   says it should be (``app.name`` everywhere), not against the two
   differing literal strings in the legacy files.

2. **Chaos blast radius.** The legacy Schedule uses
   ``mode: fixed-percent, value: "50"``. PRD §7.6 explicitly specifies a
   gentler default product behavior ("kills exactly one pod at random, not
   all replicas"). The podchaos template uses ``mode: one`` — the functional
   spec overrides the legacy manifest's literal historical value here.

3. **Resource requests/limits.** The legacy Deployment has no
   ``resources:`` block at all. PRD §9 specifies default CPU/memory
   requests and limits as a schema field, so the template adds that block —
   this is implementing a specified schema field, not inventing content.

4. **Service type.** The legacy Service is ``type: LoadBalancer``. The
   default is now ``ClusterIP`` (``app.serviceType``, still overridable): the
   documented access path (``nexus deploy``'s own success message) is
   ``kubectl port-forward``, which works against any Service type, while
   ``LoadBalancer`` sits ``<pending>`` forever on a bare Kind/Minikube
   cluster and provisions a real, billed load balancer per app on a real
   cloud one. A product-level correction, not a legacy-fidelity gap — see
   ``docs_site/cloud/index.md``.

Every other field (probe paths/timings, container port, image, replicas,
env vars, ArgoCD sync policy, PrometheusRule alerting logic, Grafana
dashboard panel structure) is asserted to match the legacy manifests'
structure exactly, using values driven by the flask-demo example's own
nexus.yaml (which reproduces the legacy demo's real values: image
kelyonnnn17/nexus-app:v1, port 5050, healthPath /healthz, replicas 2).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nexus_cli.core import config, render
from nexus_cli.core.output import NexusError

FLASK_DEMO = Path(__file__).resolve().parents[2] / "examples" / "flask-demo" / "nexus.yaml"


@pytest.fixture
def flask_demo_config() -> config.NexusConfig:
    return config.load(FLASK_DEMO)


@pytest.fixture
def rendered(flask_demo_config: config.NexusConfig) -> dict[str, str]:
    return render.render_manifests(flask_demo_config)


# --- template selection (PRD §9 monitoring/chaos toggles) ---


def test_default_config_renders_core_and_monitoring_not_chaos(rendered: dict[str, str]) -> None:
    assert set(rendered) == {
        "namespace",
        "serviceaccount",
        "deployment",
        "service",
        "argocd-app",
        "pdb",  # flask-demo's replicas: 2 renders it
        "prometheus-rules",
        "grafana-dashboard",
    }


def test_chaos_true_adds_podchaos_template(flask_demo_config: config.NexusConfig) -> None:
    flask_demo_config.platform.chaos = True
    rendered = render.render_manifests(flask_demo_config)
    assert "podchaos" in rendered


def test_monitoring_false_drops_monitoring_templates(flask_demo_config: config.NexusConfig) -> None:
    flask_demo_config.platform.monitoring = False
    rendered = render.render_manifests(flask_demo_config)
    assert "prometheus-rules" not in rendered
    assert "grafana-dashboard" not in rendered


def test_metrics_path_unset_omits_servicemonitor(flask_demo_config: config.NexusConfig) -> None:
    rendered = render.render_manifests(flask_demo_config)
    assert "servicemonitor" not in rendered


def test_metrics_path_set_adds_servicemonitor(flask_demo_config: config.NexusConfig) -> None:
    flask_demo_config.app.metricsPath = "/metrics"
    rendered = render.render_manifests(flask_demo_config)
    assert "servicemonitor" in rendered


def test_metrics_path_set_but_monitoring_false_omits_servicemonitor(
    flask_demo_config: config.NexusConfig,
) -> None:
    """A ServiceMonitor is a monitoring-stack resource — no monitoring stack
    installed means no ServiceMonitor, regardless of metricsPath.
    """
    flask_demo_config.app.metricsPath = "/metrics"
    flask_demo_config.platform.monitoring = False
    rendered = render.render_manifests(flask_demo_config)
    assert "servicemonitor" not in rendered


# --- namespace.yaml.j2 ---


def test_namespace_matches_legacy_structure(rendered: dict[str, str]) -> None:
    (doc,) = render.parse_documents(rendered["namespace"])
    assert doc["apiVersion"] == "v1"
    assert doc["kind"] == "Namespace"
    assert doc["metadata"]["name"] == "nexus-app"
    assert doc["metadata"]["labels"]["managed-by"] == "nexus"


# --- deployment.yaml.j2 (legacy/k8s/deployment.yaml) ---


def test_deployment_matches_legacy_structure(rendered: dict[str, str]) -> None:
    (doc,) = render.parse_documents(rendered["deployment"])
    assert doc["apiVersion"] == "apps/v1"
    assert doc["kind"] == "Deployment"
    assert doc["metadata"]["name"] == "nexus-app"
    assert doc["metadata"]["namespace"] == "nexus-app"
    assert doc["metadata"]["labels"]["app"] == "nexus-app"
    assert doc["spec"]["replicas"] == 2  # legacy: replicas: 2
    assert doc["spec"]["selector"]["matchLabels"]["app"] == "nexus-app"

    container = doc["spec"]["template"]["spec"]["containers"][0]
    assert container["name"] == "nexus-app"
    assert container["image"] == "kelyonnnn17/nexus-app:v1"  # legacy image, verbatim
    assert container["imagePullPolicy"] == "Always"  # legacy: Always
    assert container["ports"] == [{"containerPort": 5050}]  # legacy: 5050

    env = {e["name"]: e["value"] for e in container["env"]}
    assert env == {"VERSION": "v1", "BG_COLOR": "blue"}  # legacy env, verbatim

    # legacy has no resources block; PRD §9 adds one with its documented defaults
    assert container["resources"] == {
        "requests": {"cpu": "100m", "memory": "128Mi"},
        "limits": {"cpu": "500m", "memory": "512Mi"},
    }

    for probe_name, delay, period in (("readinessProbe", 3, 5), ("livenessProbe", 5, 10)):
        probe = container[probe_name]
        assert probe["httpGet"] == {"path": "/healthz", "port": 5050}  # legacy: /healthz, 5050
        assert probe["initialDelaySeconds"] == delay
        assert probe["periodSeconds"] == period
        assert probe["timeoutSeconds"] == 2  # legacy: 2 for both probes
        assert probe["failureThreshold"] == 3  # legacy: 3 for both probes


# --- pod hardening (deployment.yaml.j2): securityContext, serviceAccount, ---
# --- startupProbe, topologySpreadConstraints, PDB. No legacy equivalent —  ---
# --- see nexus_cli/templates/README.md.                                    ---


def test_pod_spec_references_dedicated_service_account(rendered: dict[str, str]) -> None:
    (doc,) = render.parse_documents(rendered["deployment"])
    pod_spec = doc["spec"]["template"]["spec"]
    assert pod_spec["serviceAccountName"] == "nexus-app"
    assert pod_spec["automountServiceAccountToken"] is False
    assert pod_spec["securityContext"] == {"seccompProfile": {"type": "RuntimeDefault"}}


def test_container_security_context_always_hardened_by_default(rendered: dict[str, str]) -> None:
    """flask-demo doesn't set app.security, so only the unconditional
    hardening (safe for any image) should appear — not runAsNonRoot/
    runAsUser/readOnlyRootFilesystem, which depend on the image and default
    off (SecurityConfig's docstring in core/config.py).
    """
    (doc,) = render.parse_documents(rendered["deployment"])
    container = doc["spec"]["template"]["spec"]["containers"][0]
    assert container["securityContext"] == {
        "allowPrivilegeEscalation": False,
        "capabilities": {"drop": ["ALL"]},
    }


def test_container_security_context_honors_app_security_opt_ins(
    flask_demo_config: config.NexusConfig,
) -> None:
    flask_demo_config.app.security = config.SecurityConfig(
        runAsNonRoot=True, runAsUser=10001, readOnlyRootFilesystem=True
    )
    rendered = render.render_manifests(flask_demo_config)
    (doc,) = render.parse_documents(rendered["deployment"])
    container = doc["spec"]["template"]["spec"]["containers"][0]
    assert container["securityContext"] == {
        "allowPrivilegeEscalation": False,
        "capabilities": {"drop": ["ALL"]},
        "runAsNonRoot": True,
        "runAsUser": 10001,
        "readOnlyRootFilesystem": True,
    }


def test_startup_probe_present_and_matches_health_path(rendered: dict[str, str]) -> None:
    (doc,) = render.parse_documents(rendered["deployment"])
    container = doc["spec"]["template"]["spec"]["containers"][0]
    assert container["startupProbe"]["httpGet"] == {"path": "/healthz", "port": 5050}
    assert container["startupProbe"]["periodSeconds"] * container["startupProbe"][
        "failureThreshold"
    ] >= 120


def test_topology_spread_present_above_one_replica(rendered: dict[str, str]) -> None:
    """flask-demo has replicas: 2."""
    (doc,) = render.parse_documents(rendered["deployment"])
    pod_spec = doc["spec"]["template"]["spec"]
    assert pod_spec["topologySpreadConstraints"] == [
        {
            "maxSkew": 1,
            "topologyKey": "kubernetes.io/hostname",
            "whenUnsatisfiable": "ScheduleAnyway",
            "labelSelector": {"matchLabels": {"app": "nexus-app"}},
        }
    ]


def test_topology_spread_absent_at_one_replica(flask_demo_config: config.NexusConfig) -> None:
    """The negative case: at replicas: 1 there's nothing to spread, and a
    required (not just preferred) constraint would have no way to be
    satisfied at all on a single-node cluster — so this is omitted rather
    than emitted as dead weight.
    """
    flask_demo_config.app.replicas = 1
    rendered = render.render_manifests(flask_demo_config)
    (doc,) = render.parse_documents(rendered["deployment"])
    pod_spec = doc["spec"]["template"]["spec"]
    assert "topologySpreadConstraints" not in pod_spec


# --- serviceaccount.yaml.j2 ---


def test_serviceaccount_rendered_and_token_not_automounted(rendered: dict[str, str]) -> None:
    (doc,) = render.parse_documents(rendered["serviceaccount"])
    assert doc["apiVersion"] == "v1"
    assert doc["kind"] == "ServiceAccount"
    assert doc["metadata"]["name"] == "nexus-app"
    assert doc["metadata"]["namespace"] == "nexus-app"
    assert doc["automountServiceAccountToken"] is False


# --- pdb.yaml.j2 ---


def test_pdb_present_at_two_replicas(rendered: dict[str, str]) -> None:
    """flask-demo has replicas: 2."""
    (doc,) = render.parse_documents(rendered["pdb"])
    assert doc["apiVersion"] == "policy/v1"
    assert doc["kind"] == "PodDisruptionBudget"
    assert doc["metadata"]["name"] == "nexus-app"
    assert doc["metadata"]["namespace"] == "nexus-app"
    assert doc["spec"]["maxUnavailable"] == 1
    assert doc["spec"]["selector"]["matchLabels"] == {"app": "nexus-app"}


def test_pdb_absent_at_one_replica(flask_demo_config: config.NexusConfig) -> None:
    """The negative case is the interesting one: maxUnavailable: 1 at
    replicas: 1 would mean 0 replicas may ever be voluntarily down, which
    blocks a node drain forever instead of protecting availability.
    """
    flask_demo_config.app.replicas = 1
    rendered = render.render_manifests(flask_demo_config)
    assert "pdb" not in rendered


# --- service.yaml.j2 (legacy/k8s/service.yaml) ---


def test_service_matches_legacy_structure(rendered: dict[str, str]) -> None:
    (doc,) = render.parse_documents(rendered["service"])
    assert doc["apiVersion"] == "v1"
    assert doc["kind"] == "Service"
    assert doc["metadata"]["name"] == "nexus-app"
    assert doc["metadata"]["namespace"] == "nexus-app"
    assert doc["spec"]["selector"]["app"] == "nexus-app"
    # Named ("http") since Phase 3 (PRD §10.4): a ServiceMonitor references a
    # Service's port by name, not number — see servicemonitor.yaml.j2.
    assert doc["spec"]["ports"] == [
        {"name": "http", "protocol": "TCP", "port": 80, "targetPort": 5050}
    ]
    # ClusterIP, not legacy's LoadBalancer — deviation #4 above.
    assert doc["spec"]["type"] == "ClusterIP"


def test_service_adds_no_extra_port_when_metrics_share_app_port(
    flask_demo_config: config.NexusConfig,
) -> None:
    flask_demo_config.app.metricsPath = "/metrics"  # metricsPort unset -> defaults to app.port
    rendered = render.render_manifests(flask_demo_config)
    (doc,) = render.parse_documents(rendered["service"])
    assert len(doc["spec"]["ports"]) == 1
    assert doc["spec"]["ports"][0]["name"] == "http"


def test_service_type_overridable(flask_demo_config: config.NexusConfig) -> None:
    flask_demo_config.app.serviceType = "LoadBalancer"
    rendered = render.render_manifests(flask_demo_config)
    (doc,) = render.parse_documents(rendered["service"])
    assert doc["spec"]["type"] == "LoadBalancer"


def test_service_adds_metrics_port_when_it_differs_from_app_port(
    flask_demo_config: config.NexusConfig,
) -> None:
    flask_demo_config.app.metricsPath = "/metrics"
    flask_demo_config.app.metricsPort = 9100
    rendered = render.render_manifests(flask_demo_config)
    (doc,) = render.parse_documents(rendered["service"])
    assert doc["spec"]["ports"] == [
        {"name": "http", "protocol": "TCP", "port": 80, "targetPort": 5050},
        {"name": "metrics", "protocol": "TCP", "port": 9100, "targetPort": 9100},
    ]


# --- servicemonitor.yaml.j2 ---


def test_servicemonitor_carries_release_label_prometheus_requires(
    flask_demo_config: config.NexusConfig,
) -> None:
    """kube-prometheus-stack's Prometheus only scrapes ServiceMonitors
    matching its serviceMonitorSelector — confirmed against a live cluster's
    actual Prometheus CR (`release: kube-prom-stack`), not assumed.
    """
    flask_demo_config.app.metricsPath = "/metrics"
    rendered = render.render_manifests(flask_demo_config)
    (doc,) = render.parse_documents(rendered["servicemonitor"])
    assert doc["apiVersion"] == "monitoring.coreos.com/v1"
    assert doc["kind"] == "ServiceMonitor"
    assert doc["metadata"]["namespace"] == "nexus-app"
    assert doc["metadata"]["labels"]["release"] == "kube-prom-stack"
    assert doc["spec"]["selector"]["matchLabels"]["app"] == "nexus-app"
    assert doc["spec"]["endpoints"] == [{"port": "http", "path": "/metrics", "interval": "15s"}]


def test_servicemonitor_references_metrics_port_when_separate(
    flask_demo_config: config.NexusConfig,
) -> None:
    flask_demo_config.app.metricsPath = "/metrics"
    flask_demo_config.app.metricsPort = 9100
    rendered = render.render_manifests(flask_demo_config)
    (doc,) = render.parse_documents(rendered["servicemonitor"])
    assert doc["spec"]["endpoints"][0]["port"] == "metrics"


# --- argocd-app.yaml.j2 (legacy/application.yaml) ---


def test_argocd_app_matches_legacy_structure(rendered: dict[str, str]) -> None:
    (doc,) = render.parse_documents(rendered["argocd-app"])
    assert doc["apiVersion"] == "argoproj.io/v1alpha1"
    assert doc["kind"] == "Application"
    assert doc["metadata"]["name"] == "nexus-app"
    assert doc["metadata"]["namespace"] == "argocd"  # legacy: argocd
    assert doc["metadata"]["labels"]["managed-by"] == "nexus"  # PRD §10.1 app discovery
    assert doc["spec"]["project"] == "default"  # legacy: default
    # repoURL/branch are pass-throughs of the user's own config, not derived from legacy
    assert doc["spec"]["source"]["repoURL"] == "https://github.com/kelyonn/nexus.git"
    assert doc["spec"]["source"]["targetRevision"] == "cli-platform"
    assert doc["spec"]["source"]["path"] == "k8s"  # legacy: k8s
    assert doc["spec"]["destination"]["server"] == "https://kubernetes.default.svc"
    assert doc["spec"]["destination"]["namespace"] == "nexus-app"
    assert doc["spec"]["syncPolicy"]["automated"] == {"prune": True, "selfHeal": True}


# --- prometheus-rules.yaml.j2 (legacy/monitoring/prometheus-rule-*.yaml) ---


def test_prometheus_rules_matches_legacy_structure(rendered: dict[str, str]) -> None:
    docs = render.parse_documents(rendered["prometheus-rules"])
    assert len(docs) == 2  # legacy has two separate PrometheusRule files

    availability, restarts = docs
    assert availability["kind"] == "PrometheusRule"
    assert availability["metadata"]["name"] == "nexus-app-availability"
    assert availability["metadata"]["namespace"] == "monitoring"  # legacy: monitoring
    rule = availability["spec"]["groups"][0]["rules"][0]
    assert rule["alert"] == "NexusAppReplicaShortage"  # legacy alert name, verbatim
    assert 'namespace="nexus-app"' in rule["expr"]
    assert 'deployment="nexus-app"' in rule["expr"]
    assert rule["for"] == "2m"  # legacy: 2m
    assert rule["labels"]["severity"] == "warning"  # legacy: warning

    assert restarts["metadata"]["name"] == "nexus-app-restarts"
    rule = restarts["spec"]["groups"][0]["rules"][0]
    assert rule["alert"] == "NexusAppHighRestarts"  # legacy alert name, verbatim
    assert 'namespace="nexus-app"' in rule["expr"]
    assert 'container="nexus-app"' in rule["expr"]
    assert "[5m]" in rule["expr"]  # legacy: 5m window
    assert "> 3" in rule["expr"]  # legacy: threshold 3


# --- grafana-dashboard.yaml.j2 (legacy/monitoring/grafana-dashboards-configmap.yaml) ---


def test_grafana_dashboard_matches_legacy_structure(rendered: dict[str, str]) -> None:
    """One consolidated dashboard, not the four separate ones legacy has —
    same panels (derived from legacy/monitoring/grafana-dashboards-configmap.yaml),
    just laid out in one JSON body instead of split across four ConfigMap
    keys, so there's exactly one place to look at an app's health.
    """
    (doc,) = render.parse_documents(rendered["grafana-dashboard"])
    assert doc["kind"] == "ConfigMap"
    assert doc["metadata"]["namespace"] == "monitoring"
    assert doc["metadata"]["labels"]["grafana_dashboard"] == "1"  # legacy label, verbatim
    assert set(doc["data"]) == {"overview.json"}

    import json

    overview = json.loads(doc["data"]["overview.json"])
    assert overview["uid"] == "nexus-app-overview"
    assert overview["schemaVersion"] == 38  # legacy: 38
    assert overview["refresh"] == "10s"  # legacy: 10s

    panels = {p["title"]: p for p in overview["panels"]}
    assert set(panels) == {
        "Available Replicas",
        "Desired vs Available Replicas",
        "Restart Count (5m increase)",
        "CPU Usage (cores)",
        "Memory Usage (bytes)",
    }

    availability_expr = panels["Available Replicas"]["targets"][0]["expr"]
    assert 'namespace="nexus-app"' in availability_expr
    assert 'deployment="nexus-app"' in availability_expr

    restarts = panels["Restart Count (5m increase)"]
    expr = restarts["targets"][0]["expr"]
    assert 'namespace="nexus-app"' in expr
    assert 'container="nexus-app"' in expr
    # Grafana's own {{pod}} templating syntax must survive Jinja rendering untouched
    assert restarts["targets"][0]["legendFormat"] == "{{pod}}"


def test_grafana_dashboard_adds_http_panels_when_metrics_path_set(
    flask_demo_config: config.NexusConfig,
) -> None:
    """PRD §10.4's three app-level panels, appended to the same consolidated
    dashboard. PromQL uses prometheus-flask-exporter's real metric names
    (flask_http_request_total, flask_http_request_duration_seconds_bucket)
    — verified empirically against a running instance of that exporter, not
    assumed; it does NOT use the generic http_requests_total naming other
    client libraries use.
    """
    import json

    flask_demo_config.app.metricsPath = "/metrics"
    rendered = render.render_manifests(flask_demo_config)
    (doc,) = render.parse_documents(rendered["grafana-dashboard"])
    overview = json.loads(doc["data"]["overview.json"])
    panels = {p["title"]: p for p in overview["panels"]}

    assert {"HTTP Requests/sec", "HTTP 5xx Responses/sec", "HTTP P95 Latency (seconds)"} <= set(
        panels
    )

    expr = panels["HTTP Requests/sec"]["targets"][0]["expr"]
    assert "flask_http_request_total" in expr
    assert 'namespace="nexus-app"' in expr

    expr = panels["HTTP 5xx Responses/sec"]["targets"][0]["expr"]
    assert "flask_http_request_total" in expr
    assert 'status=~"5.."' in expr

    expr = panels["HTTP P95 Latency (seconds)"]["targets"][0]["expr"]
    assert "histogram_quantile(0.95" in expr
    assert "flask_http_request_duration_seconds_bucket" in expr


def test_grafana_dashboard_omits_flask_http_panels_for_non_flask_stack(
    flask_demo_config: config.NexusConfig,
) -> None:
    """A node/generic app with metricsPath set still gets scraped (the
    ServiceMonitor is stack-agnostic — see test_servicemonitor_* above) but
    must not get panels querying flask_http_request_* metric names its own
    exporter never emits.
    """
    import json

    flask_demo_config.app.metricsPath = "/metrics"
    flask_demo_config.app.stack = "node"
    rendered = render.render_manifests(flask_demo_config)
    (doc,) = render.parse_documents(rendered["grafana-dashboard"])
    overview = json.loads(doc["data"]["overview.json"])
    titles = {p["title"] for p in overview["panels"]}
    http_titles = {"HTTP Requests/sec", "HTTP 5xx Responses/sec", "HTTP P95 Latency (seconds)"}
    assert not http_titles & titles


# --- podchaos.yaml.j2 (legacy/chaos/pod-kill.yaml + pod-kill-schedule.yaml) ---


def test_podchaos_matches_legacy_structure_except_blast_radius(
    flask_demo_config: config.NexusConfig,
) -> None:
    flask_demo_config.platform.chaos = True
    rendered = render.render_manifests(flask_demo_config)
    (doc,) = render.parse_documents(rendered["podchaos"])

    assert doc["apiVersion"] == "chaos-mesh.org/v1alpha1"
    assert doc["kind"] == "Schedule"  # legacy: Schedule (not a bare PodChaos)
    assert doc["metadata"]["namespace"] == "chaos-mesh"  # legacy: chaos-mesh
    assert doc["spec"]["schedule"] == "*/30 * * * *"  # from platform.chaosSchedule
    assert doc["spec"]["historyLimit"] == 3  # legacy: 3
    assert doc["spec"]["concurrencyPolicy"] == "Forbid"  # legacy: Forbid
    assert doc["spec"]["type"] == "PodChaos"

    pod_chaos = doc["spec"]["podChaos"]
    assert pod_chaos["action"] == "pod-kill"  # legacy: pod-kill
    # Deliberate deviation from legacy's `fixed-percent: "50"` — see module docstring.
    assert pod_chaos["mode"] == "one"
    assert pod_chaos["selector"]["namespaces"] == ["nexus-app"]
    assert pod_chaos["selector"]["labelSelectors"]["app"] == "nexus-app"
    assert pod_chaos["duration"] == "1m"  # legacy: 1m


# --- rendering with a different app.name produces a fully consistent set ---


def test_image_pull_policy_propagates_to_deployment(
    flask_demo_config: config.NexusConfig,
) -> None:
    flask_demo_config.app.imagePullPolicy = "IfNotPresent"
    rendered = render.render_manifests(flask_demo_config)
    (doc,) = render.parse_documents(rendered["deployment"])
    container = doc["spec"]["template"]["spec"]["containers"][0]
    assert container["imagePullPolicy"] == "IfNotPresent"


def test_registry_unset_omits_image_pull_secrets(
    flask_demo_config: config.NexusConfig,
) -> None:
    rendered = render.render_manifests(flask_demo_config)
    (doc,) = render.parse_documents(rendered["deployment"])
    assert "imagePullSecrets" not in doc["spec"]["template"]["spec"]


def test_registry_set_adds_image_pull_secrets_referencing_derived_name(
    flask_demo_config: config.NexusConfig,
) -> None:
    flask_demo_config.app.registry = config.RegistryConfig(
        server="ghcr.io", usernameEnv="REG_USER", passwordEnv="REG_PASS"
    )
    rendered = render.render_manifests(flask_demo_config)
    (doc,) = render.parse_documents(rendered["deployment"])
    assert doc["spec"]["template"]["spec"]["imagePullSecrets"] == [
        {"name": flask_demo_config.app.registry_secret_name}
    ]


# --- app.secrets -> secretKeyRef (core/secrets.py automation) ---


def test_secrets_unset_omits_env_block_entirely(
    flask_demo_config: config.NexusConfig,
) -> None:
    flask_demo_config.app.env = []
    rendered = render.render_manifests(flask_demo_config)
    (doc,) = render.parse_documents(rendered["deployment"])
    assert "env" not in doc["spec"]["template"]["spec"]["containers"][0]


def test_secrets_set_renders_secret_key_ref_with_no_value_key(
    flask_demo_config: config.NexusConfig,
) -> None:
    """The load-bearing assertion: a secretKeyRef entry has no `value:` key
    at all — the actual secret never passes through this template, only a
    reference to a key in a Secret core/secrets.py applies separately.
    """
    flask_demo_config.app.secrets = [
        config.SecretVar(name="DB_PASSWORD", valueEnv="APP_DB_PASSWORD")
    ]
    rendered = render.render_manifests(flask_demo_config)
    assert "APP_DB_PASSWORD" not in rendered["deployment"]

    (doc,) = render.parse_documents(rendered["deployment"])
    container = doc["spec"]["template"]["spec"]["containers"][0]
    secret_entries = [e for e in container["env"] if e["name"] == "DB_PASSWORD"]
    assert secret_entries == [
        {
            "name": "DB_PASSWORD",
            "valueFrom": {
                "secretKeyRef": {
                    "name": flask_demo_config.app.secret_name,
                    "key": "DB_PASSWORD",
                }
            }
        }
    ]
    assert "value" not in secret_entries[0]


def test_secrets_coexist_with_plain_env_vars(
    flask_demo_config: config.NexusConfig,
) -> None:
    flask_demo_config.app.secrets = [
        config.SecretVar(name="DB_PASSWORD", valueEnv="APP_DB_PASSWORD")
    ]
    rendered = render.render_manifests(flask_demo_config)
    (doc,) = render.parse_documents(rendered["deployment"])
    container = doc["spec"]["template"]["spec"]["containers"][0]
    names = {e["name"] for e in container["env"]}
    # flask-demo's own env (VERSION, BG_COLOR — see test_deployment_matches_legacy_structure)
    assert names == {"VERSION", "BG_COLOR", "DB_PASSWORD"}


def test_secrets_only_no_plain_env_still_adds_env_block(
    flask_demo_config: config.NexusConfig,
) -> None:
    flask_demo_config.app.env = []
    flask_demo_config.app.secrets = [
        config.SecretVar(name="DB_PASSWORD", valueEnv="APP_DB_PASSWORD")
    ]
    rendered = render.render_manifests(flask_demo_config)
    (doc,) = render.parse_documents(rendered["deployment"])
    container = doc["spec"]["template"]["spec"]["containers"][0]
    assert "env" in container
    assert len(container["env"]) == 1


def test_secret_name_derived_from_app_name(flask_demo_config: config.NexusConfig) -> None:
    assert flask_demo_config.app.secret_name == "nexus-app-secrets"
    assert flask_demo_config.app.registry_secret_name == "nexus-app-registry"


# --- injection hardening (see docs/INTERVIEW-BRIEF.md) ---
#
# `EnvVar.value` is deliberately NOT schema-validated (test_config.py's
# test_env_value_stays_free_text) — users need to put arbitrary strings
# there, so `config.load()` can't be the fix for this field. Safety comes
# from `| tojson` escaping every YAML-scalar interpolation in the templates
# themselves. These tests render the *verified* payload (confirmed, before
# this fix, to make `securityContext: {privileged: true}` land on the
# container) and prove it now round-trips as inert data instead.

_QUOTE_BREAKOUT_PAYLOAD = (
    'x"\n        securityContext:\n          privileged: true\n        stdin: "true'
)

_EXPECTED_CONTAINER_KEYS = {
    "name",
    "image",
    "imagePullPolicy",
    "securityContext",
    "ports",
    "env",
    "resources",
    "startupProbe",
    "readinessProbe",
    "livenessProbe",
}


def test_env_value_quote_breakout_no_longer_injects(
    flask_demo_config: config.NexusConfig,
) -> None:
    flask_demo_config.app.env = [config.EnvVar(name="HOSTILE", value=_QUOTE_BREAKOUT_PAYLOAD)]
    rendered = render.render_manifests(flask_demo_config)
    (doc,) = render.parse_documents(rendered["deployment"])
    container = doc["spec"]["template"]["spec"]["containers"][0]

    # No sibling key was injected onto the container...
    assert set(container) == _EXPECTED_CONTAINER_KEYS
    # ...and specifically, the payload's own `securityContext: {privileged:
    # true}` did not merge into (or override) the real securityContext this
    # template always renders — it's still exactly the hardened, harmless
    # value, with no `privileged` key anywhere in it.
    assert container["securityContext"] == {
        "allowPrivilegeEscalation": False,
        "capabilities": {"drop": ["ALL"]},
    }
    assert "stdin" not in container

    # And the value survives byte-exact as inert data, since this field must
    # stay usable for legitimate free-text values.
    env = {e["name"]: e["value"] for e in container["env"]}
    assert env["HOSTILE"] == _QUOTE_BREAKOUT_PAYLOAD


def test_env_value_with_plain_quote_still_parses(
    flask_demo_config: config.NexusConfig,
) -> None:
    """Before the fix, a value as mundane as `say "hi"` produced unparseable
    YAML (an availability bug, not just a security one) — the unescaped
    `value: "{{ var.value }}"` broke on the embedded quote alone.
    """
    flask_demo_config.app.env = [config.EnvVar(name="MSG", value='say "hi"')]
    rendered = render.render_manifests(flask_demo_config)
    (doc,) = render.parse_documents(rendered["deployment"])
    container = doc["spec"]["template"]["spec"]["containers"][0]
    env = {e["name"]: e["value"] for e in container["env"]}
    assert env["MSG"] == 'say "hi"'


def test_hostile_env_value_across_every_template_still_parses(
    flask_demo_config: config.NexusConfig,
) -> None:
    """The durable regression guard: render every template this config can
    produce (monitoring + chaos both on) with a hostile env value present,
    and confirm every document is still parseable YAML with no unexpected
    top-level structure. `env.value` is the only field that reaches a
    template without being schema-restricted to a safe charset (see
    test_config.py's injection-hardening suite for the rest), so it's the
    one that has to be proven safe at the template layer.
    """
    import json

    flask_demo_config.app.env = [config.EnvVar(name="HOSTILE", value=_QUOTE_BREAKOUT_PAYLOAD)]
    flask_demo_config.app.metricsPath = "/metrics"
    flask_demo_config.platform.chaos = True

    rendered = render.render_manifests(flask_demo_config)
    assert set(rendered) == {
        "namespace",
        "serviceaccount",
        "deployment",
        "service",
        "argocd-app",
        "pdb",  # flask-demo's replicas: 2 renders it
        "prometheus-rules",
        "grafana-dashboard",
        "servicemonitor",
        "podchaos",
    }

    # Every Nexus-generated resource has this shape; namespace.yaml.j2 has no
    # spec (a Namespace has none), serviceaccount.yaml.j2 puts
    # automountServiceAccountToken at the top level (not under spec — a
    # ServiceAccount has no spec either), and grafana-dashboard.yaml.j2 is a
    # ConfigMap (data, not spec) — all three are the known exceptions,
    # everything else must match exactly.
    base_keys = {"apiVersion", "kind", "metadata"}
    expected_by_name = {
        "namespace": base_keys,
        "serviceaccount": base_keys | {"automountServiceAccountToken"},
        "grafana-dashboard": base_keys | {"data"},
    }
    for name, text in rendered.items():
        expected = expected_by_name.get(name, base_keys | {"spec"})
        for doc in render.parse_documents(text):
            assert isinstance(doc, dict)
            assert set(doc) == expected
            if name == "grafana-dashboard":
                for payload in doc["data"].values():
                    json.loads(payload)  # every dashboard body is still valid JSON

    # The one place the payload should actually show up: as inert env data.
    (deploy_doc,) = render.parse_documents(rendered["deployment"])
    container = deploy_doc["spec"]["template"]["spec"]["containers"][0]
    assert set(container) == _EXPECTED_CONTAINER_KEYS


# --- render_template() and the malformed-YAML defense-in-depth check ---


def test_render_template_renders_single_named_template(
    flask_demo_config: config.NexusConfig,
) -> None:
    """`render_template` (used by e.g. `nexus chaos schedule enable` to apply
    one manifest imperatively) goes through the same `_render_and_verify`
    path as `render_manifests` — exercised here for real, not monkeypatched
    away, unlike its one existing caller in tests/unit/test_chaos.py.
    """
    text = render.render_template("podchaos", flask_demo_config)
    (doc,) = render.parse_documents(text)
    assert doc["kind"] == "Schedule"


def test_render_and_verify_raises_nexus_error_on_malformed_yaml_output() -> None:
    """Defense in depth (core/render.py's `_render_and_verify`): if a
    template ever produced malformed YAML — despite schema validation and
    `| tojson` escaping — it must fail as a clear NexusError before reaching
    `kubectl apply`, not surface a raw parser traceback. The real templates
    can no longer be forced into producing invalid YAML (that's the point of
    the rest of this test file), so this simulates the failure with a
    deliberately broken template to prove the safety net itself works.
    """
    import jinja2

    broken_env = jinja2.Environment(
        loader=jinja2.DictLoader({"broken.yaml.j2": "key: [unclosed"})
    )
    with pytest.raises(NexusError) as exc_info:
        render._render_and_verify(broken_env, "broken", {})
    assert "broken.yaml.j2" in exc_info.value.what


def test_different_app_name_is_consistent_across_all_templates(
    flask_demo_config: config.NexusConfig,
) -> None:
    flask_demo_config.app.name = "my-other-app"
    flask_demo_config.platform.chaos = True
    rendered = render.render_manifests(flask_demo_config)

    names_seen = set()
    for doc in render.parse_documents(rendered["namespace"]):
        names_seen.add(doc["metadata"]["name"])
    for doc in render.parse_documents(rendered["deployment"]):
        names_seen.add(doc["metadata"]["namespace"])
    for doc in render.parse_documents(rendered["service"]):
        names_seen.add(doc["metadata"]["namespace"])
    for doc in render.parse_documents(rendered["podchaos"]):
        names_seen.add(doc["spec"]["podChaos"]["selector"]["namespaces"][0])

    assert names_seen == {"my-other-app"}
