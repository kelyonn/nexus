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
