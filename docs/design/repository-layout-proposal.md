# Repository layout and module boundary proposal

[中文](repository-layout-proposal.zh.md) · [Current system overview](../backend-workflow-system-design.zh-en.md) · [Four-layer contract](../multilingual-production-interfaces.zh.md)

Status: **proposal for review, not approval to migrate**. Evidence date: 2026-10-02. Original inventory baseline: [dev@84e9d71d24ae86170efbb4c57755246f369ec9d9][baseline]. Amendment review baseline: [dev@8c64502404f9ae7110ee49aa990bcaeb2f8cd24d][review-baseline], fetched and checked against the remote branch on 2026-10-02. The original counts below remain tied to the original baseline; the delta inventory in §1.1 covers the amendment review. This document designs directory ownership, dependency boundaries and migration gates. It does not change production contracts or claim that the proposed packages, directories or unified execution capabilities already exist.

Keep one multilingual monorepo. Separate clients, services, reusable production code, deployment configuration and experiments at the top level; express L1–L4 within the production package. Establish dependency direction before moving modules. Confirm implementation scope and sequencing only after the cloud Source/DAG diagnostic line and the local Spark performance line finish and their results are reconciled.

## 1 Evidence and scope

The business contracts are relatively clear; the physical organization still reflects the prototype's growth:

- `scripts/` contains 338 tracked files, including 296 directly at its root, mixing CLIs, production libraries, infrastructure capabilities and experiments.
- `backend/app.py` imports production modules from `scripts`, while production scripts import shared adapters such as `backend.cloud`. This is a directory-level bidirectional dependency, not proof that every path has a runtime circular-import failure. [API imports][api-imports], [production entry imports][pipeline-imports]
- Production UI staging reads `experiments/sermon-dubbing-poc/web/`. The same POC contains an actual Firebase Functions/Firestore feedback service. [UI source][ui-source], [feedback service][feedback]
- Hosting assembly reads shared reader source from `firebase/dev/public/`, so an environment directory also holds source and content packages. [Reader source][reader-source]
- `schemas/` already contains 52 versioned contracts. `apps/tongxing-ios/` already has useful Core, Infrastructure, App and test boundaries.

Counts refer to the pinned Git tree, not executed test cases. No model execution, deployment or device acceptance was rerun for this proposal.

**This change adds only the English and Chinese design files.** It moves no code and changes no `AGENTS.md`, backlog, shared documentation index, entrypoint, CI, configuration or deployment target. It does not merge another branch or authorize deployment, infrastructure changes, data migration or paid reruns.

### 1.1 Amendment delta inventory

The PR head reviewed before this amendment was `a3dcff3bdb3df111409b49d87f19deafc2554391`. Its two design files were unchanged from `52759ffb977c36224959d0832593becaef59978e`; that head had merged dev, not refreshed the design. The following assignments reconcile the original inventory with the pinned amendment baseline and active Tracker design. They are ownership decisions for later migration, not implementation or deployment evidence.

| Evidence at amendment review | Proposed owner | Boundary to preserve |
|---|---|---|
| Existing fingerprint Node CLI and browser worker both consume the same algorithm | `packages/fingerprint/`; Python runtime adapter in production compute | Two actual consumers already justify the shared package; no production runtime dependency on an app checkout (§3.1) |
| Existing `tracker-admin/` UI, publisher, sanitizer and Firebase/Firestore files | Four distinct owners in §3.2 | Public reads, authenticated writes and private evidence remain separate |
| `sermon_fresh_source_stages.py`, `sermon_fresh_source_prefect.py`, `sermon_fresh_full_dag.py`, `sermon_mock_tts_{contract,control,dag,worker}.py` added after the original inventory | Keep experimental until promotion is decided; later engine/controller adapters in orchestration, synthetic workers in compute, stage semantics in the relevant stage | Preserve synthetic/diagnostic qualifications; no native GPU, human approval or production publication inferred from a real Prefect engine. [Fresh DAG][fresh-dag], [mock DAG][mock-dag] |
| `sermon_durable_accounting.py` and changed log outbox/completion behavior | Durable event delivery in observability; safe file/lock primitives in storage; completion shape in contracts and evidence validation with its owning review/orchestration consumer | Extract shared I/O APIs before moving imports of workflow-job helpers; preserve append/ACK crash recovery, immutable facts, opt-in behavior and synthetic versus production completion domains. [Durable accounting][durable-accounting], [outbox][review-outbox], [completion][completion] |
| Updated `sermon_log_contract.py` validation/schema caches, including merged PR #221 | Observability contract validation; packaged schema supplied through contracts | Preserve exact typed/schema identity, 8,192-entry/16 MiB dual bounds, success-only caching and fork reset; full-byte reads, hashes and durable sequence/conflict authority remain independent. [Log validator][review-log-validator] |
| `experiments/local_experiment_log/` | Remain experiments; only demonstrated stable measurement entrypoints may later move to tools/benchmarks | Reuse the canonical validator/writer/outbox; no second production log authority or automatic permission to run GPU trials. [Experiment contract][local-log] |
| `ci_change_scope.py`, sharded runner and current Web/Swift contract routing | tools/development plus existing workflow location | Test discovery, fixture ownership and required-check routing must migrate together (§5.5). [Python discovery][test-discovery], [Python CI][python-ci], [iOS routing][ios-ci] |
| Planned `build_tracker_dag_projection.py`, nested DAG snapshot, frontend `dag.js` / `snapshot-state.js` and extra sanitizer | Same four Tracker boundaries in §3.2 | Active design, **not present in the pinned dev baseline**; reconcile the final reviewed files and public schema before any move |

SparkHub/resource-guardian implementations remain in their own repositories. This proposal owns only this repository's explicit compute adapters and versioned exchange contracts; it does not absorb those projects or enable their execution gates. Recheck the final revisions of both experiment lines and any further cache/Tracker PRs before implementation.

## 2 Proposed target tree

This is the complete review target, not a request to create empty directories. Establish each directory only when it has actual contents and a clear responsibility. Conditional entries remain where they are until their stated condition is resolved.

```text
repository/
├── apps/
│   ├── tongxing-ios/                    # Preserve current Xcode / SwiftPM modules
│   ├── listening-web/                   # Production weekly listening client
│   │   ├── src/                        # JS / CSS / templates using existing build capabilities
│   │   ├── public/                     # Authored static assets, not generated weekly releases
│   │   ├── tests/
│   │   └── package.json
│   ├── tracker-web/                     # Read-only public tracker client, no privileged publisher
│   ├── operator-web/                    # Conditional on inventory of legacy web/ consumers
│   └── support-web/                     # Existing static support and privacy pages
├── services/
│   ├── api/                            # Python HTTP, auth, request mapping, worker entrypoints
│   │   ├── src/tongxing_api/
│   │   ├── tests/
│   │   ├── pyproject.toml
│   │   └── Dockerfile
│   └── feedback/                       # Functions + Firestore feedback and anonymous usage
│       ├── src/
│       ├── tests/
│       └── package.json
├── packages/
│   ├── fingerprint/                     # Shared browser algorithm and Node runtime CLI
│   │   ├── src/
│   │   ├── bin/
│   │   ├── tests/
│   │   └── package.json
│   └── production/                     # One installable Python package initially
│       ├── pyproject.toml
│       ├── src/tongxing_production/
│       │   ├── cli/                    # Arguments, exit codes and stable command registration
│       │   ├── source/                 # L1 English facts, media identity, anchors and package
│       │   ├── text/                   # L2 text, language policy and locale plugins
│       │   ├── audio/                  # L3 speech jobs, audio, synchronization and voice eligibility
│       │   ├── delivery/               # L4 release, catalog, publication and verification
│       │   ├── workflows/              # Composition for prepared, dual_pdf and live_session scopes
│       │   ├── live/                   # Existing real-time session capabilities
│       │   ├── orchestration/          # Jobs, leases, scheduling, recovery and engine adapters
│       │   ├── compute/                # Providers, model workers and device/resource adapters
│       │   ├── observability/          # Events / accounting / projections
│       │   ├── storage/                # Local/GCS I/O, object publication and atomic writes
│       │   ├── contracts/              # Contract loading, identity and common validation types
│       │   ├── review/                 # Cross-layer receipts, fixed gates and revisions
│       │   └── adapters/legacy/        # Still-used historical contracts, without eligibility upgrades
│       └── tests/                      # Unit tests organized by the same responsibilities
├── schemas/                            # Keep current path and single authored JSON Schema source
├── config/                             # Keep non-secret production policies and review configuration
├── infra/
│   ├── firebase/                       # Hosting/Functions deployment and CORS configuration
│   └── cloud-run/                      # Conditional on moving actual deployment definitions
├── tools/
│   ├── ops/                            # Operations, preflight and diagnostic CLIs
│   │   └── tracker-publisher/           # Privileged publisher/watch and mandatory public sanitizer
│   ├── benchmarks/                     # Stable reusable performance/quality measurement entrypoints
│   └── development/                    # Repository and CI tooling
├── experiments/                        # Unpromoted research with status, environment and exit criteria
├── tests/
│   ├── integration/                    # Cross-package workflows and recovery
│   ├── contracts/                      # Web / iOS / Python consistency checks
│   └── fixtures/
│       └── contracts/                  # Single source for shared synthetic, non-secret fixtures
├── data/                               # Controlled reference data and frozen benchmark inputs
├── docs/
│   ├── design/                         # Proposals and architecture decisions with status and baseline
│   ├── workflows/                      # User workflows
│   ├── reports/                        # Dated evidence, not a replacement for current contracts
│   └── ...                             # Preserve existing contract/runbook links initially
├── scripts/                            # Transitional legacy command wrappers
├── artifacts/                          # Ignored outputs, caches, receipts, logs, builds and checkpoints
├── requirements.txt                    # Transitional compatibility; environment migration is separate
├── requirements-prefect.txt             # Existing optional runtime, not a forced universal lock
└── .github/workflows/                   # Preserve required check names and triggering semantics
```

### 2.1 Clients and platforms

`listening-web` is a client; Firebase Hosting is its hosting mechanism. Functions runs a service, Firestore stores data, and Storage/CORS belongs to deployment and storage configuration. Firebase-related files therefore do not all belong to the frontend, and `backend/` is not the whole backend. [Firebase project model][firebase-docs]

Create `operator-web` only after checking active consumers of `web/`. That directory currently contains both an operator interface and a public congregation caption page. Preserve the public entry, potentially as a separate entrypoint in the same package, and document its name and deployment target. Do not promote `experiments/local-live-poc/` merely by moving it.

`support-web` receives existing support/privacy pages and may remain plain static files. The Web `src/public/tests` split expresses ownership; preserve URLs, CSP, module imports and existing build capabilities rather than introducing a framework or rewriting the UI.

### 2.2 Four layers inside production

| Layer | Directory | Output and boundary |
|---|---|---|
| L1 Shared English Source & Anchors | `source/` | English Source Package; changed source identity invalidates every locale |
| L2 Target-Language Text | `text/` | One Candidate per locale; machine review remains separate from human approval |
| L3 Target-Language Audio & Synchronization | `audio/` | Same-locale Audio Package; preserve actual eligibility limits of explicit `audio_unavailable` |
| L4 Multilingual Delivery & Playback | `delivery/` | One Release per pageId + targetLocale, aggregated into the catalog under its contract |

L4 production assembles and publishes; Web/iOS consume releases from `apps/`. L4 cannot repair text/audio or upgrade upstream review. `workflows/dual_pdf` and `live/` keep their actual scopes: naming cannot turn legacy outputs into `four_layer_release`. Voice training/model research remains separate from weekly production, without adding an L5. [Four-layer contract][layers]

## 3 Ownership and dependency rules

Ownership below is a code responsibility, not an assignment to an unconfirmed person or team.

| Module | Owns | Does not own |
|---|---|---|
| apps | Presentation, player, device cache and interaction | Generation, inferred approval or service credentials |
| services | HTTP/events, auth, request mapping and deployment entrypoints | Duplicated production rules inside handlers |
| source/text/audio/delivery | Stage transformations, artifact validation and explicit side effects | A second global scheduler or bypass of upstream gates |
| workflows | Composition for a named workflow scope | A second job store or retry authority |
| orchestration | Durable jobs, leases, cancellation, deadlines, scheduling and reconciliation | Editing approved text or retrying unknown outcomes as failures |
| compute | Model/API transport, worker lifetime, resource/device adapters and execution receipts | Human approval, publication eligibility or content-driven failover |
| review | Hash-bound review receipts, deterministic admission and revision relationships | Human approval by proxy or dashboard-driven eligibility writes |
| observability | Events, costs/timing and traceable projections | Replacing authoritative business state with a log status |
| storage | Atomic I/O, safe paths, object operations and CAS primitives | Deciding which content may be published |
| contracts + schemas | Schema loading, identity and field contracts | Importing applications, model runtimes or CLIs |

Recommended dependency direction:

```text
apps/services/CLIs/experiments → workflows or explicit stage public APIs
workflows → orchestration + source/text/audio/delivery
orchestration → stage public interfaces + compute/storage/review
stage business logic → contracts/review + injected compute/storage/event interfaces
foundation interfaces/contracts → no dependency back on workflows/services/clients
```

Rules:

1. Production packages must not import `apps/`, `services/`, `tools/`, `scripts/` or `experiments/`. This also forbids resolving subprocess programs or runtime resources from those source trees. Experiments may consume production packages. Declared shared packages may be consumed through explicit APIs/runtime adapters.
2. Stages exchange versioned packages, receipts and explicit public APIs rather than arbitrary internal paths. A high-level assembler legitimately reads several packages.
3. `contracts/` contains common shape/identity validation. Stage-specific semantic checks stay with their stage; it is not a container for all shared-looking business code.
4. `observability/events` is a lightweight interface. `observability/projections` reads existing contract evidence; neither imports controllers to re-execute work. Extract event interfaces before moving code to avoid low-level logging depending on workflows.
5. Prefect, Temporal and existing supervisor integrations remain adapters. Experiment results determine which become supported production paths. Layout does not choose an engine or authorize a competing approval/retry ledger.
6. Export public interfaces instead of downstream imports of `_safe_path`, `_digest` and other private implementations. Add equivalent public APIs and tests before switching callers; do not combine that move with behavioral changes.
7. Do not create a generic `utils/` dumping ground. Hash/JSON, media, storage and provider functions follow their responsibilities. Extract lightweight common code only for demonstrated stable consumers.

### 3.1 Shared fingerprint runtime

The [Python L1 path][fingerprint-runtime] executes `build_fingerprint_index.mjs` during production and hashes both that CLI and `web/fingerprint-core.mjs`. The [Node CLI][fingerprint-cli] and [browser worker][fingerprint-worker] already consume the same core. Assign the algorithm and Node CLI to `packages/fingerprint/`; the browser bundles the public algorithm API, while a production compute adapter invokes the declared, installed CLI. L1 source identity and L4 final-track binding remain business responsibilities of their stages.

The adapter receives an explicit runtime location/version rather than finding `apps/listening-web` through repository-relative paths. Deployment installs the shared package and its required Node/ffmpeg runtime through a declared artifact/resource manifest. A Python wheel import smoke is insufficient: verify an installed, non-repository-CWD precompute/bind fixture without an app source checkout. The app and pipeline must neither fork the algorithm nor depend on each other's private source files.

Migration preserves CLI modes/flags, stdout JSON, exit/error behavior, source/window/track binding, algorithm version, output bytes and manifest hashes. Moving or editing the CLI/core may change implementation identity: record real new hashes, retain old frozen runtime manifests, and add exact compatibility mappings only after equivalence tests. Do not bypass cache or historical receipt validation merely because the algorithm's name is unchanged.

### 3.2 Tracker projection and publication boundaries

The existing `experiments/sermon-dubbing-poc/tracker-admin/` contains both a browser client and an ADC-authenticated [publisher][tracker-publisher]; it is not a frontend-only directory. Its [Firestore rules][tracker-rules] allow public snapshot reads and deny client writes. The following four-way split is required; moving the entire directory to an app or treating it all as observability is not equivalent.

| Boundary | Proposed owner | Allowed input/output |
|---|---|---|
| Private evidence projection and public export | `production/observability/projections/` | Read verified accounting/progress/receipt evidence; produce a versioned, bounded public allowlist projection. No execution, ledger repair or approval writes |
| Read-only presentation | `apps/tracker-web/` | Consume only the public snapshot contract; display freshness and observed/planned/unknown states. No raw ledger, ADC or publisher dependency |
| Authenticated publication/watch and independent sanitization | `tools/ops/tracker-publisher/` | Own the CLI, Firebase Admin dependency and runtime credential use; revalidate/allowlist the candidate before its sole Firestore write path |
| Hosting/database deployment and access policy | `infra/firebase/` | Own Hosting targets, CSP, database IDs, rules and indexes; preserve separate Dev/Production destinations and existing access semantics |

The read-only portions of `weekly_pipeline_report.py`, `four_layer_measure.py` and `build_four_layer_tracker_snapshot.py` belong to the projection side after separating CLI/I/O wrappers and producer instrumentation. Timing/event writers stay on the lightweight event/accounting side; projection code must not acquire a command-execution or ledger-write capability. The operator-maintained `four_layer_progress.py` ledger remains explicitly non-authoritative for production gates; its write commands must not become a browser or projection capability. The existing private `source-video-state.private.json` stays outside Hosting outputs and Firestore. [Snapshot builder][tracker-builder]

Keep both the Python public export boundary and the independent Node [sanitizer][tracker-sanitizer]. Sanitize **before transmission**, never only in the browser; unknown fields must be dropped or rejected. The publisher must not import privileged behavior from the frontend bundle. Use one versioned public contract and shared positive/negative fixtures to keep both checks aligned. Raw paths, private hashes/execution identities, provider messages, credentials and private source state cannot be added to public data by copying an internal report. Publish only explicitly allowed safe categories/counts, statuses, bounded timing and already approved links; missing evidence stays unknown and synthetic/planned data stays labeled.

The active DAG enhancement is planned to add `build_tracker_dag_projection.py`, a nested versioned snapshot, a DAG sanitizer, `src/dag.js` and `src/snapshot-state.js` in today's paths. These are **planned files at this review baseline**, not evidence that dev already implements the feature. Its selected-run/page/target/ledger binding, reconnect freshness and observed-versus-planned distinctions must survive migration. The publisher remains the sole writer. Real review submission, private evidence access and production control require separately reviewed authenticated services and are outside this directory change.

## 4 Current to target mapping

Confidence describes responsibility assignment; risk describes migration impact. High confidence does not mean safe to move immediately. Keep filenames initially to avoid combining relocation, renaming and rewrites. In this table, `production/` abbreviates `packages/production/src/tongxing_production/`, not another root directory.

| Current path or group | Proposed destination | Confidence / risk | Required care |
|---|---|---|---|
| `apps/tongxing-ios/` | Keep in place | High / low | Preserve player authority, project paths and modules |
| `experiments/sermon-dubbing-poc/web/` | `apps/listening-web/` | High / high | Production source today; check build, CSP, relative imports and historical URLs |
| Reader source in `firebase/dev/public/` | Separate reader entry/adapter in listening-web | High / high | Identify one source owner per file; do not overwrite one reader with another |
| Its content/packages/releases/catalog data | Synthetic samples to fixtures; real releases remain release artifacts | Medium / high | Classify frozen public fixtures/evidence first; no bulk deletion or real data copied into new source |
| `web/` | Conditional `apps/operator-web/` | Medium / high | Preserve public caption entry and backend serving consumers |
| `firebase/tongxing-support/public/` | `apps/support-web/` | High / medium | Preserve page URLs, legal text and links |
| `experiments/sermon-dubbing-poc/feedback-api/` | `services/feedback/` | High / high | Preserve function ID, database, service account, retention and routing |
| `experiments/sermon-dubbing-poc/tracker-admin/` plus Python Tracker projections | Four owners in §3.2 | High / high | Split UI, private/public projection, privileged publisher/sanitizer and infra; retain public allowlists and private state isolation |
| `backend/app.py`, `cloud_run_jobs.py`, HTTP worker glue | `services/api/src/tongxing_api/` | High / high | Thin handlers gradually; preserve API/auth/command behavior |
| Reusable parts of `backend/cloud.py`, `storage.py` | production storage and minimal provider/secret adapters | High / high | Runtime-injected secrets; split business helpers rather than blindly moving whole files |
| `backend/realtime.py`, `live_playback.py` | production live plus service protocol shell | Medium / high | Preserve session/archive contracts and separation from prepared production |
| English Source builder/judge and source/anchor logic | `production/source/` | High / high | Preserve English/anchor and machine/human evidence boundaries |
| MFA backend/Spark execution adapters | `production/compute/`; L1 semantics stay in source | High / high | Preserve original deadline, MFA identity, failover reason and cache binding |
| Candidate producer, target-language policy and locale plugins | `production/text/` | High / high | Plugin paths and implementation hashes require explicit compatibility |
| `run_target_language_models.py` | L2 logic in text; provider transport in compute | High / high | Preserve model roles, request identity, budget and human review |
| Speech job, formal renderer, audio builder/screen/review | production audio; hardware workers in compute | High / high | Verify batch/window/seed, reuse, checkpoint, voice and back-ASR receipts independently |
| Multilingual assembly, formal staging, deploy and verify modules | `production/delivery/` | High / high | Preserve v2/v3/legacy boundaries, allowlists and historical assets |
| Supervisor, canonical jobs/controllers, workflow jobs and execution harness | `production/orchestration/`, file by file | High / high | Do not move every canonical-prefixed file by a pattern |
| Prefect DAG/flows and `sermon_temporal/` | Engine adapters or retained experiments | Medium / high | Wait for results; preserve mock/synthetic/diagnostic labels |
| Logs, accounting and trace/progress projections | `production/observability/` | High / high | Preserve events, clock domains, cost attribution and execution identity |
| Shared review/gate/revision primitives | production review/contracts | High / high | L2-specific logic stays in text; no new approval authority |
| Post-live/local production entrypoints | production workflows plus CLI | High / high | Preserve dual_pdf/legacy versus four_layer_release scopes |
| `sermon_pipeline.py` | Gradual extraction into source/text/compute/workflows | High / high | Equivalent function extraction; retain original facade initially |
| POC `build_fingerprint_index.mjs` and `web/fingerprint-core.mjs` | `packages/fingerprint/`; explicit production compute adapter | High / high | Existing Python and browser consumers share one runtime artifact; no app-source dependency, hash/CLI/cache compatibility per §3.1 |
| Stable benchmark code in `scripts/experiments/` | tools benchmarks; unstable approaches remain experiments | Medium / medium | Preserve inputs, sampling, identities and measurement definitions |
| Firebase Hosting JSON, CORS and deployment templates | `infra/firebase/` | High / high | Separate Dev/Production; validate config-relative paths |
| `schemas/`, `config/` | Keep in place initially | High / low | Specify ownership/loading instead of introducing needless path changes |
| Tests and cross-client fixtures | Local unit tests; shared contracts under root fixtures | High / medium | Generate SwiftPM resource copies from one source and check hashes |

This is a responsibility map, not an executable glob-based move list. Each migration PR must enumerate actual files, consumers, identity/data effects and rollback.

## 5 Contracts configuration resources and environments

### 5.1 Schema and fixture ownership

- Keep `schemas/` as the only editable schema source. Stages own their schema semantics; cross-cutting review/accounting owners own theirs. Producer and Web/iOS consumers jointly validate client-contract changes.
- Do not hand-maintain duplicate schemas in language-specific directories. Model types may be generated or authored, but must pass the same golden/negative fixtures. Introducing code generation is not a prerequisite.
- `production/contracts/` loads and validates rather than redefining contracts. A future wheel build may copy the root schemas into package resources through an explicit manifest, verifying source hashes. These are generated build copies, never a second editable source. Installed code uses `importlib.resources`, not checkout/CWD discovery.
- Policies stay under `config/`, selected through explicit configuration and bound by hash. Secrets come only from runtime injection or existing secret providers, never from wheels, example configurations or client bundles.
- Fixtures must be synthetic, sanitized or explicitly authorized public data. Keep current frozen `data/benchmarks` references/evidence unchanged until a separate archival decision; volume alone is not grounds for deletion.

### 5.2 Source location is not a working directory

Pass artifact/cache/config roots through an explicit `RunContext` or equivalent parameters while preserving formats and safe-path rules. New package APIs must not infer the repository through `Path(__file__).parents[...]`. Static assets are package resources or declared build inputs. Transitional wrappers may resolve old default locations, with tests from outside the repository CWD.

Generate client release directories into ignored outputs; do not use hand-edited `infra/.../public` as source. Infra points to declared build outputs. Docker/Functions packaging must include required schemas, templates, static assets, data slices and subprocess programs. Successful Python imports alone do not prove a working container.

### 5.3 Python packages and hardware runtimes

Start with one production `pyproject.toml` and one API project, not a wheel or microservice for each layer. SwiftPM/Xcode and Node retain their toolchains.

Maintain ordinary Python, optional Prefect/Temporal, Spark CUDA and Mac MLX dependencies separately. Basic production imports must not load torch, MLX or orchestration SDKs. Explicitly chosen adapters load optional runtimes lazily and preserve classified missing-dependency failures. Tool choice remains open; do not force incompatible runtimes into one lockfile/venv. [uv workspace limitations][uv-docs]

Spark-first/Mac fallback remains limited to allowed infrastructure/runtime failures. Content failures, identity mismatch, pending human review and unknown remote outcomes still require stopping or reconciliation. The tree does not claim automatic cross-host dispatch for all canonical producers. [Compute policy][compute-policy]

### 5.4 SQL and tools

There are no tracked `.sql` files at the baseline. Prefect/Temporal SQLite is tool state, while Firestore is current service storage. Do not create an empty SQL directory. If a business SQL database is introduced, migrations follow its owning service; read-only analysis queries follow the analytics tool, based on actual use.

`tools/` holds operational/development/measurement entrypoints and tool-specific logic. Reusable business code belongs in production. Transitional `scripts/` must not become a second permanent implementation tree.

### 5.5 Test discovery and inventory equivalence

The current [sharded Python runner][test-discovery] discovers only root `tests/`; package-local tests will not run just because files moved under `packages/production/tests/` or `services/api/tests/`. The current [Python workflow][python-ci] also invokes POC Python, listener and feedback suites by explicit paths. [SwiftPM fixtures][swift-fixtures] are bundled under Core tests and are read by both Python and Web consumers. Preserve that coverage as one migration batch, not at a later cleanup phase.

For every test move, capture a pre-move manifest of suites and discovered test IDs without executing model/deployment work. Record a one-to-one old/new test-ID mapping for path/module renames; the after-move union must cover every previous test, with intentional additions/removals explicitly reviewed. Compare inventory per runtime/suite, not only aggregate counts: duplicate facade discovery must not hide a missing suite. Discovery/import failures fail the gate. Keep package-qualified IDs for sharding/timing so identically named modules in two packages do not collide, and map old timing weights explicitly rather than silently dropping them.

Add the new package/service discovery roots, installed-package/non-repository-CWD tests, shared JS fingerprint tests and Tracker projection/sanitizer/frontend tests to the relevant runner/workflow commands in the same PR that moves them. Do not count a documented but unexecuted suite as covered. Regenerate SwiftPM fixture resource copies from the single shared source and compare hashes; update all Python/Node readers and Swift resource declarations together. Exercise rename/delete routing and preserve the required `unittest` and `native-client` aggregators. A green required check is insufficient if its expected test inventory shrank unexpectedly.

## 6 Command compatibility and execution identity

Inventory existing commands, `python -m` paths, arguments, stdout JSON, exit codes, environment variables and default artifact locations. Add thin wrappers calling public package APIs and verify old commands before updating consumers. Do not use symlinks to evade path-safety checks. Final console entrypoint names follow that inventory; this proposal does not advertise unimplemented commands.

**Behavioral equivalence does not imply identity equivalence.** Existing sensitive bindings include:

1. The Prefect pilot hashes specific source paths in `CLOSURE`, saves code identity in `runtime.json`, and revalidates it on resume. [Code identity][code-identity]
2. Locale policies bind plugin implementation/dependency hashes. Source compatibility already uses exact old/new source allowlists for narrowly scoped read-only historical reuse. [Plugin identity][plugin-identity], [Source compatibility][source-compat]
3. Formal TTS distinguishes sound-semantic identity from actual execution implementation hashes and freezes batch/window/seed and cache/reuse policies. Moving paths, adapters or environments does not authorize mixing prior sound. [Renderer identity][renderer]

Migration safeguards:

- Active jobs finish on their frozen revision, runtime, code and artifact/cache directories. No hot replacement, renumbering or overwritten receipts.
- Prefer retaining a recoverable old revision/environment with input/configuration, code manifest, tool/model/checkpoint identity and original lock/ledger locations.
- New execution receives new code identity. Existing versioned compatibility rules decide artifact reuse. Any accepted hash change needs an exact old/new mapping, bounded scope, input/output bindings and independent tests, not a generic version-mismatch bypass.
- Do not alter hashing or manufacture historical hashes to avoid recomputation. Preserve sound-semantic identity only after explicit independent equivalence review; always record actual execution code hashes.
- Regress original deadlines, budgets, lease fencing, cancellation, unknown outcomes and existing single-dispatch/admission guarantees. A move must not reset a budget or generate another model call.

## 7 Decisions gated on the experiment results

Freeze structural changes to the active execution closure: Source/MFA identity, strict L2/diagnostics, DAG/session adapters, logs/accounting, renderer/batching/ASR/resources, related schemas and recovery directories. Use the actual run plans/manifests to determine the closure rather than filename prefixes. Design review can proceed.

| Pending evidence | Effect on implementation | Can be reviewed now |
|---|---|---|
| Cloud Source/DAG outcome and recovery evidence | Supported orchestration/diagnostic adapters versus continuing experiments | Client/service/production boundaries |
| Spark component, throughput and recovery results | Compute adapters, runtime isolation, batching and remote reconciliation APIs | Separating hardware from L1–L4 business logic |
| Cross-line logs/cost/clock/completion contracts | Event/projection APIs and compatibility layers | Observation cannot grant approval or execution authority |
| Current Web/legacy consumer inventory | Reader ownership, conditional operator app and retirement criteria | Firebase platform versus client source |

Experiment completion does not automatically approve migration. Refresh dev, inspect intervening files and review proposal deltas and per-batch scope first.

## 8 Migration sequence and rollback

All phases occur only after both experiment lines finish and the relevant implementation scope is confirmed. Use separate PRs for responsibility-equivalent moves/extractions. Behavioral changes belong in separate PRs.

| Phase | Work | Exit criterion |
|---|---|---|
| 0 Baseline | Inventory entrypoints, call graph, targets, code/resources, schemas and experiment outcomes | Active jobs recoverable; every production POC dependency assigned |
| 1 Package boundary | Add package skeleton and one low-coupling extraction with legacy import/CLI facades | Installed/non-repo-CWD smoke; no new reverse dependencies |
| 2 Product sources | Move listener, feedback, support and the four Tracker boundaries by unique ownership; decide operator separately | Equivalent build manifest; unchanged URLs/CSP/API/database configuration; no privileged code/private evidence in client output |
| 3 Foundation and stages | Establish contract/review/event/storage interfaces, then extract L1–L4 in batches | Golden, failure, identity and recovery tests for each stage |
| 4 Orchestration and compute | Connect selected engine/compute adapters through public APIs | Unchanged concurrency/cancel/lease/budget/unknown behavior; no duplicate work |
| 5 Build and entrypoint completion | Complete Docker/resources/CI routes/runbooks | Required checks route correctly; old/new CLI parity; rollback available |
| 6 Compatibility retirement | Remove only wrappers with no active consumers; version historical docs | Empty consumer inventory, old jobs terminal and rollback window confirmed |

Each batch updates its necessary build and CI paths immediately. Phase 5 is final consolidation, not permission to leave phases 1–4 unbuildable. Roll back code/configuration to the matching revision while retaining artifacts and audit history. Do not delete old assets, rewrite ledgers or force-rewrite Git history as rollback.

Move the shared fingerprint runtime before, or atomically with, switching its Python/browser callers; never leave an intermediate dependency on app source. A Tracker move carries its exporter/sanitizer contract, publisher entrypoint and access-policy fixtures together. Test-discovery inventory equivalence from §5.5 is an exit condition for every affected phase. Neither this documentation amendment nor either experiment's completion authorizes merging into dev or starting a migration; both lines must finish and the user must renew the implementation decision.

## 9 Acceptance gates

### This design change

- Exactly two new `docs/design/` files; no source, entrypoint, CI, configuration, backlog or shared index changes.
- English/Chinese target trees, phases, constraints and key mappings agree. Relative links and pinned source links refer to actual paths.
- `git diff --check` and the existing documentation-only gate pass. Keep the PR in draft; do not merge.
- Record the exact amended head and comparison base in the PR verification report after committing; verify the pushed remote SHA and CI for that SHA. The prior `52759ff...` checks are historical, not validation of this amendment. Link/source checks and bilingual tree comparison are separate from CI completion; pending or skipped runtime/device checks remain explicitly pending or not run.
- CI success describes documentation validation only, not completed migration, model execution or device acceptance.

### Future migration batches

- **Structure:** no production imports from experiments/tools/entrypoints, no new cycles, explicit public APIs, resource ownership and runtime requirements.
- **Behavior:** fixture output fields, states, hashes, stdout/exit codes and failure classification match. Enumerate permitted differences; green tests alone are not proof of semantic equivalence.
- **Recovery:** old jobs resume under frozen revisions; identities do not mix; test cancellation, original deadlines, budget, leases, unknown outcomes, reconciliation and duplicate requests.
- **Artifacts:** schema/shared-fixture parity; preserve scope, review status, actual text-only capability, locale independence and historical package readability.
- **Build:** clean install/package; all runtime resources in wheel/Docker/Functions; non-repository CWD works; optional CUDA/MLX does not contaminate basic imports.
- **Tests:** affected Python shards, package/service installed tests, shared fingerprint and Node listener/feedback/Tracker suites, and Swift Core/storage/shared-contract tests. Require the reviewed before/after discovery inventory mapping in §5.5 and fixture-copy hashes. Add device/interaction checks for UI changes. Select full scope from actual impact.
- **CI:** preserve required `unittest` and `native-client` names; new paths and renames/deletions route correctly without permanently pending or false-skipped checks.
- **Release:** candidate-only allowlist/hash/Range and historical-asset checks. Actual deployment and Web/iOS/venue acceptance retain their separate authorization/evidence requirements.

## 10 References and rationale

Separating apps/services from reusable packages is a common monorepo convention. Directory spelling and adopting Turborepo are not requirements. [Turborepo's official structure guide][turbo-docs] illustrates the principle, not a universal Python/Swift build system.

Keep root schemas/configuration, iOS and externally consumed command paths initially to avoid low-value compatibility breaks. Start with one production Python package rather than premature services. Reconsider additional packages when independent release, ownership or dependency-isolation needs actually arise.

[baseline]: https://github.com/JonathanJing/sermon-video-zh-subtitles/commit/84e9d71d24ae86170efbb4c57755246f369ec9d9
[review-baseline]: https://github.com/JonathanJing/sermon-video-zh-subtitles/commit/8c64502404f9ae7110ee49aa990bcaeb2f8cd24d
[fingerprint-runtime]: https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/8c64502404f9ae7110ee49aa990bcaeb2f8cd24d/scripts/sermon_pipeline.py#L1552-L1575
[fingerprint-cli]: https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/8c64502404f9ae7110ee49aa990bcaeb2f8cd24d/experiments/sermon-dubbing-poc/build_fingerprint_index.mjs#L1-L6
[fingerprint-worker]: https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/8c64502404f9ae7110ee49aa990bcaeb2f8cd24d/experiments/sermon-dubbing-poc/web/fingerprint-worker.mjs
[tracker-publisher]: https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/8c64502404f9ae7110ee49aa990bcaeb2f8cd24d/experiments/sermon-dubbing-poc/tracker-admin/publish.mjs#L57-L107
[tracker-sanitizer]: https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/8c64502404f9ae7110ee49aa990bcaeb2f8cd24d/experiments/sermon-dubbing-poc/tracker-admin/sanitize.mjs#L92-L115
[tracker-rules]: https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/8c64502404f9ae7110ee49aa990bcaeb2f8cd24d/experiments/sermon-dubbing-poc/tracker-admin/firestore.rules
[tracker-builder]: https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/8c64502404f9ae7110ee49aa990bcaeb2f8cd24d/scripts/build_four_layer_tracker_snapshot.py#L514-L560
[fresh-dag]: https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/8c64502404f9ae7110ee49aa990bcaeb2f8cd24d/scripts/sermon_fresh_full_dag.py
[mock-dag]: https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/8c64502404f9ae7110ee49aa990bcaeb2f8cd24d/scripts/sermon_mock_tts_dag.py
[durable-accounting]: https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/8c64502404f9ae7110ee49aa990bcaeb2f8cd24d/scripts/sermon_durable_accounting.py
[review-outbox]: https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/8c64502404f9ae7110ee49aa990bcaeb2f8cd24d/scripts/sermon_log_outbox.py#L13-L15
[completion]: https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/8c64502404f9ae7110ee49aa990bcaeb2f8cd24d/scripts/sermon_completion.py
[review-log-validator]: https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/8c64502404f9ae7110ee49aa990bcaeb2f8cd24d/scripts/sermon_log_contract.py
[local-log]: https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/8c64502404f9ae7110ee49aa990bcaeb2f8cd24d/experiments/local_experiment_log/README.zh.md
[test-discovery]: https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/8c64502404f9ae7110ee49aa990bcaeb2f8cd24d/scripts/run_unittest_ci.py#L90-L118
[python-ci]: https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/8c64502404f9ae7110ee49aa990bcaeb2f8cd24d/.github/workflows/python-tests.yml
[ios-ci]: https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/8c64502404f9ae7110ee49aa990bcaeb2f8cd24d/.github/workflows/tongxing-ios.yml#L45-L102
[swift-fixtures]: https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/8c64502404f9ae7110ee49aa990bcaeb2f8cd24d/apps/tongxing-ios/Core/Package.swift#L8-L10
[api-imports]: https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/84e9d71d24ae86170efbb4c57755246f369ec9d9/backend/app.py#L11-L44
[pipeline-imports]: https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/84e9d71d24ae86170efbb4c57755246f369ec9d9/scripts/run_post_live_subtitle_generation.py#L24-L39
[ui-source]: https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/84e9d71d24ae86170efbb4c57755246f369ec9d9/scripts/stage_production_ui.py#L80-L85
[feedback]: https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/84e9d71d24ae86170efbb4c57755246f369ec9d9/experiments/sermon-dubbing-poc/feedback-api/index.mjs
[reader-source]: https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/84e9d71d24ae86170efbb4c57755246f369ec9d9/scripts/assemble_multilingual_hosting.py#L212-L220
[layers]: https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/84e9d71d24ae86170efbb4c57755246f369ec9d9/docs/multilingual-production-interfaces.zh.md
[compute-policy]: https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/84e9d71d24ae86170efbb4c57755246f369ec9d9/docs/local-production-compute-policy.zh.md
[code-identity]: https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/84e9d71d24ae86170efbb4c57755246f369ec9d9/scripts/sermon_prefect_dag.py#L33-L81
[plugin-identity]: https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/84e9d71d24ae86170efbb4c57755246f369ec9d9/scripts/produce_target_language_candidate.py#L55-L80
[source-compat]: https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/84e9d71d24ae86170efbb4c57755246f369ec9d9/scripts/sermon_source_producer_compatibility.py
[renderer]: https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/84e9d71d24ae86170efbb4c57755246f369ec9d9/scripts/render_formal_target_language_speech.py
[firebase-docs]: https://firebase.google.com/docs/projects/learn-more
[uv-docs]: https://docs.astral.sh/uv/concepts/projects/workspaces/#when-not-to-use-workspaces
[turbo-docs]: https://turborepo.dev/docs/crafting-your-repository/structuring-a-repository
