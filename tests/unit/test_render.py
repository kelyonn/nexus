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

Every other field (probe paths/timings, container port, image, replicas,
env vars, service type, ArgoCD sync policy, PrometheusRule alerting logic,
Grafana dashboard panel structure) is asserted to match the legacy manifests'
structure exactly, using values driven by the flask-demo example's own
nexus.yaml (which reproduces the legacy demo's real values: image
kelyonnnn17/nexus-app:v1, port 5050, healthPath /healthz, replicas 2).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nexus_cli.core import config, render

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
        "deployment",
        "service",
        "argocd-app",
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
    assert doc["spec"]["type"] == "LoadBalancer"  # legacy: LoadBalancer


def test_service_adds_no_extra_port_when_metrics_share_app_port(
    flask_demo_config: config.NexusConfig,
) -> None:
    flask_demo_config.app.metricsPath = "/metrics"  # metricsPort unset -> defaults to app.port
    rendered = render.render_manifests(flask_demo_config)
    (doc,) = render.parse_documents(rendered["service"])
    assert len(doc["spec"]["ports"]) == 1
    assert doc["spec"]["ports"][0]["name"] == "http"


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
    (doc,) = render.parse_documents(rendered["grafana-dashboard"])
    assert doc["kind"] == "ConfigMap"
    assert doc["metadata"]["namespace"] == "monitoring"
    assert doc["metadata"]["labels"]["grafana_dashboard"] == "1"  # legacy label, verbatim

    # legacy has exactly these four dashboards
    assert set(doc["data"]) == {
        "app-availability.json",
        "pod-restarts.json",
        "resource-usage.json",
        "replica-status.json",
    }

    import json

    availability = json.loads(doc["data"]["app-availability.json"])
    assert availability["uid"] == "nexus-app-availability"
    assert availability["schemaVersion"] == 38  # legacy: 38
    assert availability["refresh"] == "10s"  # legacy: 10s
    expr = availability["panels"][0]["targets"][0]["expr"]
    assert 'namespace="nexus-app"' in expr
    assert 'deployment="nexus-app"' in expr

    restarts = json.loads(doc["data"]["pod-restarts.json"])
    expr = restarts["panels"][0]["targets"][0]["expr"]
    assert 'namespace="nexus-app"' in expr
    assert 'container="nexus-app"' in expr
    # Grafana's own {{pod}} templating syntax must survive Jinja rendering untouched
    assert restarts["panels"][0]["targets"][0]["legendFormat"] == "{{pod}}"


def test_grafana_dashboard_adds_http_panels_when_metrics_path_set(
    flask_demo_config: config.NexusConfig,
) -> None:
    """PRD §10.4's three app-level panels. PromQL uses prometheus-flask-
    exporter's real metric names (flask_http_request_total,
    flask_http_request_duration_seconds_bucket) — verified empirically
    against a running instance of that exporter, not assumed; it does NOT
    use the generic http_requests_total naming other client libraries use.
    """
    import json

    flask_demo_config.app.metricsPath = "/metrics"
    rendered = render.render_manifests(flask_demo_config)
    (doc,) = render.parse_documents(rendered["grafana-dashboard"])

    assert {"http-request-rate.json", "http-error-rate.json", "http-latency.json"} <= set(
        doc["data"]
    )

    requests = json.loads(doc["data"]["http-request-rate.json"])
    assert requests["uid"] == "nexus-app-requests"
    expr = requests["panels"][0]["targets"][0]["expr"]
    assert "flask_http_request_total" in expr
    assert 'namespace="nexus-app"' in expr

    errors = json.loads(doc["data"]["http-error-rate.json"])
    assert errors["uid"] == "nexus-app-errors"
    expr = errors["panels"][0]["targets"][0]["expr"]
    assert "flask_http_request_total" in expr
    assert 'status=~"5.."' in expr

    latency = json.loads(doc["data"]["http-latency.json"])
    assert latency["uid"] == "nexus-app-latency"
    expr = latency["panels"][0]["targets"][0]["expr"]
    assert "histogram_quantile(0.95" in expr
    assert "flask_http_request_duration_seconds_bucket" in expr


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
    assert flask_demo_config.app.registry_secret_name == "nexus-app-registry"


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
