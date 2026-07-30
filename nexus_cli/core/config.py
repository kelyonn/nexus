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
# Kubernetes' own env-var-name convention (C_IDENTIFIER-ish, what kubelet
# recommends) — deliberately also the charset that can't break out of an
# unquoted Jinja scalar in deployment.yaml.j2's `name: {{ var.name }}`.
# `| tojson` at the template layer is the real fix (this survives even if a
# template later drops it); this is belt-and-suspenders at the schema layer,
# and it also just rejects env var names no Kubernetes container would accept.
_ENV_NAME_RE = re.compile(r"^[-._a-zA-Z][-._a-zA-Z0-9]*$")
# A conservative, allow-listed charset for anything that ends up interpolated
# into generated YAML/PromQL/JSON: letters, digits, and `.-_/`. No quotes, no
# whitespace, no control characters, no YAML/git metacharacters — so nothing
# in this charset can break out of a scalar or a URL path, full stop.
_SAFE_PATH_RE = re.compile(r"^/[\w./\-]*$")
_SAFE_BRANCH_RE = re.compile(r"^[\w.\-/]+$")
# A narrow, deliberately-not-exhaustive deny-list for app.env entries that
# look like credentials (see _validate_no_plaintext_secrets below). Biased
# toward false positives over false negatives — `PASS` also matches
# PASSWORD/PASSWD, and `TOKEN` will flag legitimate non-secret names like
# MAX_TOKENS — both have a one-line escape hatch (`plaintext: true`), which is
# a better trade than missing a real credential. Deliberately excludes
# entropy/base64/length heuristics: those need constant tuning and produce
# false positives on digests, UUIDs, and version strings for no real gain
# over this list for the common case (see FUTURE-SCOPE.md §1 for what a more
# thorough answer — Sealed Secrets/SOPS — would look like).
_SECRET_NAME_RE = re.compile(
    r"PASS|SECRET|TOKEN|API_?KEY|PRIVATE_KEY|CREDENTIAL|DSN|DATABASE_URL|CONNECTION_STRING",
    re.IGNORECASE,
)
_URL_USERINFO_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://[^/\s]*:[^/@\s]+@")
_PEM_HEADER_RE = re.compile(r"-----BEGIN ")


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
    # Escape hatch for a false positive from _validate_no_plaintext_secrets
    # below (e.g. an env var genuinely named MAX_TOKENS that isn't a
    # credential). Deliberately a schema field, not a CLI flag: the decision
    # to bypass the check lives in the committed nexus.yaml, visible in code
    # review forever, not passed invisibly on the command line each time.
    plaintext: bool = False

    @field_validator("name")
    @classmethod
    def _env_name(cls, v: str) -> str:
        if not _ENV_NAME_RE.match(v):
            raise ValueError(
                "must be a valid environment variable name "
                "(letters, digits, '_', '.', '-'; can't start with a digit)"
            )
        return v


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


class SecretVar(BaseModel):
    """Names an environment variable to read a secret value from at deploy
    time — never the value itself. Same pattern as ``RegistryConfig`` above,
    applied to arbitrary app secrets instead of just registry credentials:
    ``nexus.yaml`` gets committed to git, so a raw secret living here would
    recreate the exact problem GitOps exists to avoid. The Deployment
    references the resulting Secret via ``valueFrom.secretKeyRef``
    (``deployment.yaml.j2``); the Secret itself is applied imperatively via
    ``kubectl`` and never rendered into ``k8s/`` or committed — see
    ``core/secrets.py``.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    valueEnv: str

    @field_validator("name")
    @classmethod
    def _secret_name(cls, v: str) -> str:
        if not _ENV_NAME_RE.match(v):
            raise ValueError(
                "must be a valid environment variable name "
                "(letters, digits, '_', '.', '-'; can't start with a digit)"
            )
        return v

    @field_validator("valueEnv")
    @classmethod
    def _value_env(cls, v: str) -> str:
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
    # Real secrets (DB passwords, API keys) for the app itself — as opposed
    # to app.env, which is free text and, by design, rejects anything that
    # looks credential-shaped (see _validate_no_plaintext_secrets). Each
    # entry names an env var to read the actual value from at deploy time;
    # nexus.yaml never holds it. See SecretVar's docstring and core/secrets.py.
    secrets: list[SecretVar] = Field(default_factory=list)

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
        if not _SAFE_PATH_RE.match(v):
            raise ValueError(
                "must start with '/' and contain only letters, digits, '.', '-', '_', '/'"
            )
        return v

    @field_validator("metricsPath")
    @classmethod
    def _metrics_path(cls, v: str | None) -> str | None:
        if v is not None and not _SAFE_PATH_RE.match(v):
            raise ValueError(
                "must start with '/' and contain only letters, digits, '.', '-', '_', '/'"
            )
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

    @property
    def secret_name(self) -> str:
        """Deterministic name for the app.secrets Secret this app's
        Deployment references via secretKeyRef (deployment.yaml.j2) — same
        single-source-of-truth reasoning as registry_secret_name above, so
        the template and core/secrets.py can't drift apart.
        """
        return f"{self.name}-secrets"


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

    @field_validator("branch")
    @classmethod
    def _branch(cls, v: str) -> str:
        # Unlike repoURL, branch had no validator at all until this fix — and
        # it lands unquoted in argocd-app.yaml.j2's `targetRevision:` and
        # flows straight to `kubectl apply` (register_argocd_app). A crafted
        # branch could rewrite sibling keys in the generated Application
        # (e.g. `spec.source.path`, `spec.syncPolicy`) — verified against
        # this template before this fix landed. The allow-listed charset
        # below (plus the git-ref sanity rules) closes that off entirely,
        # independent of the `| tojson` escaping added at the template layer.
        if (
            not _SAFE_BRANCH_RE.match(v)
            or ".." in v
            or v.startswith("-")
            or v.startswith("/")
            or v.endswith("/")
            or v.endswith(".lock")
            or v.endswith(".")
        ):
            raise ValueError(
                "must be a valid git branch name (letters, digits, '.', '-', '_', '/' only; "
                "no '..', no leading '-', no leading/trailing '/', no trailing '.' or '.lock')"
            )
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


def _validate_no_plaintext_secrets(cfg: NexusConfig) -> None:
    """Reject app.env entries that look like credentials.

    Deliberately NOT a Pydantic field/model validator, unlike every other
    rule in this file. A Pydantic ValidationError's `input` carries the raw
    value that failed — `output.from_validation_error` renders that as
    `(got: <value>)`, which is exactly the right thing for a bad `image` or
    `name`, and exactly the wrong thing here: it would echo the credential
    this check exists to keep out of any output, including the error message
    itself, straight back into the terminal (verified empirically before
    choosing this design — see docs/INTERVIEW-BRIEF.md). So this runs as a
    plain post-validation pass in `load()` instead, and its NexusError never
    includes `var.value`.
    """
    problems = []
    for i, var in enumerate(cfg.app.env):
        if var.plaintext:
            continue
        reasons = []
        if _SECRET_NAME_RE.search(var.name):
            reasons.append("its name looks credential-shaped")
        if _URL_USERINFO_RE.match(var.value):
            reasons.append("its value looks like a URL with embedded credentials")
        if _PEM_HEADER_RE.search(var.value):
            reasons.append("its value looks like a PEM-encoded key")
        if reasons:
            problems.append(f"  app.env[{i}] ('{var.name}'): {' and '.join(reasons)}")
    if not problems:
        return
    raise output.NexusError(
        what=f"{len(problems)} env var(s) in app.env look like credentials:\n"
        + "\n".join(problems),
        why=(
            "nexus.yaml (and the k8s/ manifests nexus deploy commits) get pushed to your "
            "git remote — a real credential in app.env would reach it in cleartext."
        ),
        fix=(
            "Move it to app.secrets instead (names an environment variable to read the "
            "real value from at deploy time — the value itself never touches nexus.yaml "
            "or git). If this genuinely isn't a credential, add `plaintext: true` to that "
            "app.env entry."
        ),
    )


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
        cfg = NexusConfig.model_validate(data)
    except ValidationError as exc:
        raise output.from_validation_error(exc, source=str(p)) from exc
    _validate_no_plaintext_secrets(cfg)
    return cfg
