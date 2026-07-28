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

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

_ALWAYS_ON = ("namespace", "deployment", "service", "argocd-app")
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
    if config.platform.monitoring:
        names += _MONITORING
    if config.platform.chaos:
        names += _CHAOS
    return names


def render_manifests(config: NexusConfig) -> dict[str, str]:
    """Render every applicable template for this config.

    Returns a mapping of template stem -> rendered YAML text.
    """
    env = _environment()
    context = {"app": config.app, "platform": config.platform}
    rendered = {}
    for name in template_names(config):
        rendered[name] = env.get_template(f"{name}.yaml.j2").render(**context)
    return rendered


def render_template(name: str, config: NexusConfig) -> str:
    """Render one named template, regardless of the monitoring/chaos toggles.

    Used by commands that apply a specific manifest imperatively (e.g.
    ``nexus chaos schedule enable``), where the action itself is the signal
    to render it rather than ``platform.chaos``/``platform.monitoring``.
    """
    env = _environment()
    context = {"app": config.app, "platform": config.platform}
    return env.get_template(f"{name}.yaml.j2").render(**context)


def parse_documents(text: str) -> list[dict]:
    """Parse a (possibly multi-document, ``---``-separated) YAML string."""
    return [doc for doc in yaml.safe_load_all(text) if doc is not None]
