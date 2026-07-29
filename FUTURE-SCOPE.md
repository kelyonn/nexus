# Future scope

Ideas that are real and worth doing eventually, deliberately not started
yet — either because they're a bigger scope/architecture decision than they
first look, because they carry more risk than the rest of this codebase
currently does, or because building them now would be premature relative to
where the project is (see `CLAUDE.md`'s "drop that for now, I need people to
use this first" call on telemetry — same reasoning applies here).

Each entry below has enough context to pick up cold; none of them have any
code started.

---

## 1. Secret management (Sealed Secrets or SOPS)

**The problem:** GitOps has a hard boundary — you can't commit a raw secret
(a DB password, an API key) to git, but `nexus deploy` currently has no
opinion about secrets at all. Today, a user has to solve this themselves,
entirely outside the `nexus deploy` flow.

**Why this is the one actually worth building, eventually:** unlike the
other gaps in this project, this one is a real, structural limitation of
"GitOps done simply" — not a missing convenience. Closing it would be a
genuine capability jump, not polish.

**Why it's not started:** this is the highest-risk thing on this whole list.
A bug in secret handling has actual security consequences, not just a broken
dashboard panel — and it's also the largest scope expansion this project
would have taken on (Nexus has deliberately stayed narrow so far: no
Ingress, no multi-app support, no telemetry).

**Design questions to resolve before writing any code** (this needs its own
plan-mode pass, not an ad-hoc build):

- **Sealed Secrets vs SOPS.** Sealed Secrets fits Nexus's existing pattern
  better (install a controller into the cluster, like ArgoCD/Prometheus
  already are — see `deploy.py`'s "install missing platform components"
  step) and needs no external KMS. SOPS is more flexible (works with AWS
  KMS/GCP KMS/PGP/age) but needs a key-management story Nexus doesn't have
  an opinion on today, which cuts against "one YAML file, no DevOps team."
  Leaning Sealed Secrets for that reason, but worth a real comparison.
- **The bootstrap race.** `nexus encrypt` (or wherever encryption happens)
  needs the sealing controller's public key. If a user runs `nexus deploy`
  on a fresh cluster where the controller was *just* installed in the same
  command, is the key ready yet? This is the same category of problem as
  the ArgoCD `health: Progressing` quirk and the Chaos Mesh webhook race
  already found and fixed in this project (see
  `docs_site/troubleshooting.md`) — expect a real race here too, and plan to
  live-verify it, not just unit-test it.
- **Where do sealed secrets live in `nexus.yaml`?** A new `app.secrets:`
  block? A separate `secrets.yaml` file `nexus deploy` also reads? Sealed
  Secrets' actual encrypted output (a `SealedSecret` CRD instance) is safe
  to commit — so it could plausibly render through the same
  `core/render.py` → `k8s/` → git → ArgoCD pipeline every other manifest
  already uses, which would be the more consistent design if it works.
- **Key rotation and `nexus destroy`.** What happens to a `SealedSecret`
  when the underlying keypair rotates? What does `destroy` do with secrets
  — same "namespace deletion cleans it up implicitly" pattern as everything
  else, or does secret material need more deliberate handling?
- **Local dev / CI without a cluster.** Sealed Secrets' `kubeseal` CLI
  normally needs to reach a live cluster's controller to encrypt. Decide
  whether `nexus encrypt` requires cluster access every time, or supports
  encrypting against a saved public key offline.

## 2. `environments:` schema (real overrides/inheritance in one file)

**The problem:** today, running staging + prod means maintaining two full,
mostly-duplicated `nexus.yaml` files (see `docs_site/multi-environment.md`
for the pattern that works today via `--config`). No shared base, no DRY.

**Why it's not started:** the multi-file `--config` pattern that already
works covers the actual need reasonably well for now, and this redesign
touches far more than it looks like from the outside:

- `core/config.py`'s schema, obviously.
- `core/render.py` — which config layer wins for a given field.
- **Every command's namespace/context resolution** — right now `app.name`
  *is* the namespace and the ArgoCD Application name (see
  `docs_site/multi-environment.md` — this is a hard constraint today). An
  `environments:` block would need to decide whether each environment gets
  its own namespace derived from `app.name` + environment, its own ArgoCD
  Application name, and possibly its own git branch or path automatically
  (today `platform.branch` is the thing a user manually keeps distinct per
  environment — an `environments:` block should probably manage that
  automatically instead of trusting the user to get it right, which is
  exactly the kind of footgun `docs_site/multi-environment.md` had to spend
  a full page warning about).
- The dashboard — would `nexus dashboard`'s Overview grid show one card per
  app or one per app+environment? `dashboard/backend/routes.py`'s
  `list_apps()` would need to know about environments too.

**A smaller first step, if picked up:** rather than a full inheritance
model, consider whether `nexus.yaml` gaining a `defaults:` block plus a
thin per-environment override file (`nexus.staging.yaml` containing *only*
the fields that differ) — merged by Nexus before validation — gets most of
the DRY benefit without redesigning namespace/Application-name resolution
at the same time. Worth scoping as a separate, smaller decision from "full
environments: block."

## 3. Dashboard: streaming logs (yes, later) and an exec terminal (no, not yet)

**Streaming logs in the dashboard** — reasonable, moderate effort. `nexus
logs` already exists and works via the CLI; piping that same output over a
websocket into the App Detail page (the `kubernetes` Python SDK's `stream`
functions, proxied through the FastAPI backend) is a genuine but bounded
addition. Worth doing once there's real usage to justify the investment.

**A full pod-exec terminal in the browser** — explicitly not planned for
now. This is a much bigger build than it sounds (terminal resize, signal
handling, binary framing over websockets — entire products like Lens/K9s
exist mostly to do this well), and it meaningfully raises the dashboard's
attack surface: today's dashboard is read-only-plus-a-chaos-button behind a
per-session bearer token designed for a local, loopback-only tool (see
`docs_site/architecture.md#the-dashboard`); a remote shell into arbitrary
pods is a different risk category even if it's still loopback-only. Revisit
only if there's a concrete, recurring need for it — not as a default
"nice to have."

## 4. `ClusterClient` class instead of `kubectl.py`'s stateless functions

**Not currently justified.** Every function in `nexus_cli/core/kubectl.py`
is stateless — takes explicit `namespace`/`name` params, shells out fresh
via `subprocess` each call, holds no persistent connection or context to
wrap in a class. `CLAUDE.md`'s own rule against premature abstraction
applies directly here: introduce this only if/when there's a concrete,
recurring pain point (e.g. genuinely needing to hold a long-lived
`kubernetes` Python SDK client with connection state, not just kubectl
subprocess calls) — not preemptively.

---

## Explicitly not on this list

Two suggestions from an external review of this project were checked and
found not to be real issues — noted here so they don't get re-proposed
without re-checking:

- **`httpx2` in `pyproject.toml`'s dev extras is not a typo for `httpx`.**
  Verified via `pip show httpx2` — it's a real, actively versioned package
  (`pydantic/httpx2` on GitHub, same author as the original `httpx`,
  currently 2.9.1) that provides what FastAPI's `TestClient` needs.
- **Pydantic→TypeScript type generation** was also suggested and *is* being
  built (not deferred) — see the CHANGELOG entry introducing it, not this
  file.
