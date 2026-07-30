"""Render Jinja2 manifest templates from a validated NexusConfig.

Templates in ``nexus_cli/templates/`` are parameterized versions of the
archived ``legacy/`` manifests (see docs/PRD.md §0 for the mapping table).
Rendering only fills in placeholders — it never invents new resources.

Which templates are included depends on ``platform.monitoring`` and
``platform.chaos`` (PRD §9): the core app resources (namespace, deployment,
service, ArgoCD application) are always rendered; monitoring and chaos
resources are conditional.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from nexus_cli.core.config import NexusConfig
from nexus_cli.core.output import NexusError

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

_ALWAYS_ON = ("namespace", "serviceaccount", "deployment", "service", "argocd-app")
_MONITORING = ("prometheus-rules", "grafana-dashboard")
_CHAOS = ("podchaos",)


def _environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )


def template_names(config: NexusConfig) -> list[str]:
    """The template stems that apply to this config, in render order."""
    names = list(_ALWAYS_ON)
    # A PDB only protects something that has more than one replica to
    # protect — at replicas: 1, maxUnavailable: 1 blocks every voluntary
    # disruption (node drain, cordon) forever instead of preserving
    # availability, so it's omitted rather than emitted there. See
    # pdb.yaml.j2's own comment for the full reasoning.
    if config.app.replicas >= 2:
        names.append("pdb")
    if config.platform.monitoring:
        names += _MONITORING
        # Opt-in on top of platform.monitoring: a ServiceMonitor only makes
        # sense if the app actually exposes something to scrape (PRD §10.4 —
        # see AppConfig.metricsPath's docstring for why this can't just
        # default on for every app).
        if config.app.metricsPath:
            names.append("servicemonitor")
    if config.platform.chaos:
        names += _CHAOS
    return names


def _render_and_verify(env: Environment, name: str, context: dict) -> str:
    """Render one template and confirm the result is at least parseable YAML.

    This is defense in depth, not the fix: schema validation (config.py) and
    `| tojson` escaping (the templates themselves) are what actually stop a
    hostile config value from restructuring a generated manifest — that kind
    of injection produces *valid* YAML with extra/rewritten keys, which
    parses fine and isn't caught here. What this layer catches is malformed
    YAML (e.g. an unescaped quote breaking a scalar) reaching `kubectl
    apply`, which would otherwise surface as a confusing parser error
    pointing at a file the user never directly wrote. See
    docs/INTERVIEW-BRIEF.md.
    """
    text = env.get_template(f"{name}.yaml.j2").render(**context)
    try:
        parse_documents(text)
    except yaml.YAMLError as exc:
        raise NexusError(
            what=f"Generated manifest '{name}.yaml.j2' is not valid YAML.",
            why=str(exc),
            fix=(
                "This is a bug in Nexus's template rendering, not your nexus.yaml. "
                "Please file an issue with your (redacted) config."
            ),
        ) from exc
    return text


def render_manifests(config: NexusConfig) -> dict[str, str]:
    """Render every applicable template for this config.

    Returns a mapping of template stem -> rendered YAML text.
    """
    env = _environment()
    context = {"app": config.app, "platform": config.platform}
    rendered = {}
    for name in template_names(config):
        rendered[name] = _render_and_verify(env, name, context)
    return rendered


def render_template(name: str, config: NexusConfig) -> str:
    """Render one named template, regardless of the monitoring/chaos toggles.

    Used by commands that apply a specific manifest imperatively (e.g.
    ``nexus chaos schedule enable``), where the action itself is the signal
    to render it rather than ``platform.chaos``/``platform.monitoring``.
    """
    env = _environment()
    context = {"app": config.app, "platform": config.platform}
    return _render_and_verify(env, name, context)


def parse_documents(text: str) -> list[dict]:
    """Parse a (possibly multi-document, ``---``-separated) YAML string."""
    return [doc for doc in yaml.safe_load_all(text) if doc is not None]
