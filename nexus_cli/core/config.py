"""Load and validate ``nexus.yaml`` (PRD §9).

The schema is modeled with Pydantic v2. Field constraints and ``@field_validator``
hooks enforce every rule in the PRD §9 validation table. ``load`` reads the file,
validates it, and raises a :class:`~nexus_cli.core.output.NexusError` (what/why/fix)
so callers never see a raw Pydantic traceback.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from nexus_cli.core import output

# --- validation patterns (PRD §9) ---
_NAME_RE = re.compile(r"^[a-z0-9-]+$")
# registry/image:tag — a path of name components, then a required :tag
_IMAGE_RE = re.compile(r"^[\w.\-/]+:[\w.\-]+$")
_CPU_RE = re.compile(r"^(\d+m|\d+(\.\d+)?)$")
_MEMORY_RE = re.compile(r"^\d+(Ki|Mi|Gi|Ti|Pi|Ei|K|M|G|T|P|E)?$")
_HTTPS_GIT_RE = re.compile(r"^https://[\w.\-]+(:\d+)?/[\w.\-/]+?(\.git)?$")
_SSH_GIT_RE = re.compile(r"^(ssh://)?git@[\w.\-]+[:/][\w.\-/]+?(\.git)?$")
_CRON_FIELD_RE = re.compile(r"^[\d*/,\-]+$")


def _validate_cpu(value: str) -> str:
    if not _CPU_RE.match(value):
        raise ValueError(f"not a valid Kubernetes CPU quantity (e.g. '100m', '0.5'): {value!r}")
    return value


def _validate_memory(value: str) -> str:
    if not _MEMORY_RE.match(value):
        raise ValueError(f"not a valid Kubernetes memory quantity (e.g. '128Mi'): {value!r}")
    return value


class EnvVar(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    value: str


class ResourceQuantities(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cpu: str
    memory: str

    @field_validator("cpu")
    @classmethod
    def _cpu(cls, v: str) -> str:
        return _validate_cpu(v)

    @field_validator("memory")
    @classmethod
    def _memory(cls, v: str) -> str:
        return _validate_memory(v)


class Resources(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requests: ResourceQuantities = ResourceQuantities(cpu="100m", memory="128Mi")
    limits: ResourceQuantities = ResourceQuantities(cpu="500m", memory="512Mi")


class RegistryConfig(BaseModel):
    """Names environment variables to read registry credentials from at
    deploy time — never the credentials themselves. ``nexus.yaml`` gets
    committed to git (``sync_manifests_to_git``); a raw credential living
    here would recreate the exact "secret committed to git" problem GitOps
    exists to avoid in the first place. See ``core/registry.py``.
    """

    model_config = ConfigDict(extra="forbid")

    server: str
    usernameEnv: str
    passwordEnv: str

    @field_validator("server", "usernameEnv", "passwordEnv")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty")
        return v


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=40)
    image: str
    port: int = Field(ge=1, le=65535)
    healthPath: str
    stack: Literal["node", "flask", "generic"] | None = None
    replicas: int = Field(default=2, ge=1, le=20)
    env: list[EnvVar] = Field(default_factory=list)
    resources: Resources = Field(default_factory=Resources)
    # "Always" is the safe default for a mutable `:latest`-style tag, but it's
    # exactly what makes `status.image_pull_fix()`'s Minikube advice
    # (`minikube image load`) not work — the kubelet retries the registry
    # regardless of what's already loaded locally. Users hitting
    # ImagePullBackOff on Minikube need IfNotPresent for that fix to actually
    # do anything.
    imagePullPolicy: Literal["Always", "IfNotPresent", "Never"] = "Always"
    # Opt-in: unset means "this app doesn't expose Prometheus metrics", which
    # is the honest default for an arbitrary containerized app (PRD §10.4's
    # request-rate/error-rate/latency panels need the app itself to emit
    # them — Nexus can't manufacture that data for you). Setting this renders
    # a ServiceMonitor so kube-prometheus-stack's Prometheus scrapes it.
    metricsPath: str | None = None
    metricsPort: int | None = Field(default=None, ge=1, le=65535)
    # Opt-in, same reasoning as metricsPath: unset means "this image is
    # pullable without credentials" (a public registry, or Minikube's local
    # image cache), the honest default. Setting it renders imagePullSecrets
    # on the Deployment and makes `nexus deploy` create/update the
    # underlying Secret from environment variables — see core/registry.py.
    registry: RegistryConfig | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not _NAME_RE.match(v):
            raise ValueError("must be lowercase alphanumeric and hyphens only")
        return v

    @field_validator("image")
    @classmethod
    def _image(cls, v: str) -> str:
        if not _IMAGE_RE.match(v):
            raise ValueError("must match registry/image:tag (a tag is required)")
        return v

    @field_validator("healthPath")
    @classmethod
    def _health_path(cls, v: str) -> str:
        if not v.startswith("/"):
            raise ValueError("must start with '/'")
        return v

    @field_validator("metricsPath")
    @classmethod
    def _metrics_path(cls, v: str | None) -> str | None:
        if v is not None and not v.startswith("/"):
            raise ValueError("must start with '/'")
        return v

    @property
    def effective_metrics_port(self) -> int:
        """``metricsPort`` if set, else the app's own port — most apps expose
        metrics on the same port they serve traffic on."""
        return self.metricsPort if self.metricsPort is not None else self.port

    @property
    def registry_secret_name(self) -> str:
        """Deterministic name for the imagePullSecret this app's Deployment
        references (deployment.yaml.j2) — the single source of truth both
        the template and core/registry.py use, so they can't drift apart.
        """
        return f"{self.name}-registry"


class PlatformConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repoURL: str
    branch: str
    monitoring: bool = True
    chaos: bool = False
    chaosSchedule: str = "*/30 * * * *"

    @field_validator("repoURL")
    @classmethod
    def _repo_url(cls, v: str) -> str:
        if not (_HTTPS_GIT_RE.match(v) or _SSH_GIT_RE.match(v)):
            raise ValueError("must be a valid HTTPS or SSH Git URL")
        return v

    @field_validator("chaosSchedule")
    @classmethod
    def _cron(cls, v: str) -> str:
        fields = v.split()
        if len(fields) != 5 or not all(_CRON_FIELD_RE.match(f) for f in fields):
            raise ValueError("must be a valid 5-field cron expression")
        return v


class NexusConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    app: AppConfig
    platform: PlatformConfig

    def to_yaml(self) -> str:
        """Serialize back to YAML (used by ``nexus init``)."""
        return yaml.safe_dump(self.model_dump(exclude_none=True), sort_keys=False)


def load(path: str | Path = "nexus.yaml") -> NexusConfig:
    """Load and validate a nexus.yaml file.

    Raises :class:`NexusError` (what/why/fix) on a missing file, malformed YAML,
    or any schema/validation violation.
    """
    p = Path(path)
    if not p.is_file():
        raise output.NexusError(
            what=f"No {p} found.",
            why="Nexus needs a nexus.yaml in the working directory.",
            fix="Run `nexus init` to create one, or cd into the directory that has it.",
        )
    try:
        data = yaml.safe_load(p.read_text())
    except yaml.YAMLError as exc:
        raise output.NexusError(
            what=f"{p} is not valid YAML.",
            why=str(exc),
            fix="Fix the YAML syntax and re-run.",
        ) from exc
    if not isinstance(data, dict):
        raise output.NexusError(
            what=f"{p} is empty or malformed.",
            why="Expected a YAML mapping with 'app:' and 'platform:' sections.",
            fix="Run `nexus init` to generate a valid starting point.",
        )
    try:
        return NexusConfig.model_validate(data)
    except ValidationError as exc:
        raise output.from_validation_error(exc, source=str(p)) from exc
