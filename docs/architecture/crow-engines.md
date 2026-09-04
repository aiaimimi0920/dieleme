# Crow engine architecture

Crow (乌鸦引擎) is a reusable product-intelligence system. Judicial-auction
housing is the first domain adapter, not the definition of the engine.

## Product engines and current maturity

| Engine | Responsibility | Current state |
| --- | --- | --- |
| Collection engine | Discover links, capture detail sources, and archive structured evidence | Implemented and actively used; this is the current core |
| Data analysis engine | Turn collected facts into reproducible descriptive and comparative analysis | Incomplete; existing analysis/AVM code is migration input, not a finished engine |
| Prediction engine | Produce versioned predictions with calibrated uncertainty and validation | Incomplete; no production-complete contract is claimed |

The distinction is contractual. Collection records facts and evidence. Analysis
derives explanations and comparisons. Prediction produces future or unknown
estimates. A module must not silently move a derived value into the collection
truth layer.

## Collection engine stages

### 1. Rough collection: discover links

`SeedCollectionService` owns source task intake, deduplication, raw list-payload
archiving, canonical source identity, and enqueueing detail work. It delegates
domain-specific acceptance, field aliases, and partitioning to a
`CollectionAdapter`.

Every seed should preserve, when available:

- `source_platform`
- `source_item_id`
- `source_url`
- `source_title`
- raw source fields needed for later reprocessing
- a relative path to the archived list payload

### 2. Fine collection: capture detail pages

`DetailCollectionService` owns task-facing APIs and maintenance entrypoints.
`DetailProcessor` owns the lifecycle of one captured page: AI extraction,
source archiving, artifact attachment, retry control, persistence, and cleanup.
The adapter decides whether the record belongs in the dataset, whether a
domain-specific retry is required, whether AVM risk enrichment applies, and how
the final detail record is synced. Generic detail collection never invokes the
judicial-auction AVM callbacks.

### 3. AI archive: joint evidence decision

`src.analysis_ensemble` is the compatibility API for three independent
candidate extractions, evidence locking, conflict adjudication, and final
composition. Its algorithms are source-neutral; an `AnalysisProfile` supplies
domain field types, evidence keywords, risk classification, adjudication
instructions, and derived fields.

AI output is never accepted solely because models agree. A non-system,
non-derived value must be supported by source evidence. Unsupported or
ambiguous conflicts are archived as `needs_review`.

## Domain adapters

- `GenericProductAdapter` preserves arbitrary product fields and adds only the
  canonical source identity and collection lifecycle fields. It accepts
  alphanumeric item identifiers and does not assume auctions, buildings, area,
  prices, or a sold state.
- `TaobaoJudicialAuctionAdapter` preserves the existing Taobao judicial-auction
  aliases, sold-item filtering, area retry, AVM collection record, and location
  inference prompt.
- `GenericProductAnalysisProfile` performs evidence consensus without adding
  auction-derived fields.
- `TaobaoJudicialAnalysisProfile` owns the auction/property field policy and
  unit-price derivation used by the existing workflow.

To add a new product source, implement the `CollectionAdapter` protocol and,
when AI joint archiving is needed, an `AnalysisProfile`. Inject the adapter into
the seed and detail services. Do not add another source conditional to the
orchestration services.

The service classes default to `GenericProductAdapter`. The existing HTTP server
explicitly keeps `taobao_judicial` as its compatibility default. A source-neutral
server instance can select the generic adapter without code changes:

```env
CROW_COLLECTION_ADAPTER=generic
CROW_COLLECTION_SOURCE_PLATFORM=catalog_x
```

Unknown adapter names fail during service construction instead of silently
falling back to a domain policy. New adapters should be registered in
`src/collection/adapter_resolver.py`; orchestration services remain unchanged.
Only adapters that explicitly enable `bootstraps_legacy_search_tasks` may seed
the historical Taobao location/category queue.

Each adapter also owns a `search_task_policy`. Storage owns task persistence,
leases, and status transitions; the policy owns source task identity, request
URLs, pagination, and optional sibling expansion. Generic sources register an
initial URL through `SeedCollectionService.register_search_task()`. Assigned
tasks include a stable `task_key` and `source_platform`; progress reports use
that `task_key`, the assigned `session_id`, and may provide `next_url` for the
next opaque URL cursor. Generic progress is rejected when the session no longer
owns the task lease, preventing a stale worker from advancing another worker's
cursor.
Legacy Taobao workers may continue reporting only the current `url`.

The current compatibility table persists a canonical next-request URL in
`source_url`. Sources whose cursors cannot be represented as URLs require a
separate reversible schema migration rather than overloading legacy columns.

The unattended page scanner uses a separate `seed_scan_policy` because its
state machine is a job crossed with one or more sort cursors. Generic adapters
render explicit `source_url_template` values with `category`, `location_code`,
`sort_key`, `st_param`, and `page`; Taobao keeps its historical URL and category
priority. Generic scan writes, completion, and failure also require the claiming
worker ID. The collector selects this policy through the same
`CROW_COLLECTION_ADAPTER` and `CROW_COLLECTION_SOURCE_PLATFORM` configuration.
Generic unattended scans also require `CROW_SEED_SOURCE_URL_TEMPLATE` (the
legacy alias `FAPAI_SEED_SOURCE_URL_TEMPLATE` remains accepted). Templates may
use `category`, `location_code`, `sort_key`, `st_param`, and `page` placeholders.
URL scheduling and persistence are source-neutral; the bundled unattended HTML
probe still parses Taobao payloads, so another source must inject a parser that
implements the same list-extraction boundary.

Every adapter must persist a stable `source_platform`. Repository stage tracking
uses that value to select the generic readiness contract for explicit non-Taobao
sources while retaining the Taobao judicial-auction contract for legacy records.

## Cross-cutting runtime capabilities

These capabilities support the collection engine but do not own product-domain
rules:

- storage and source-artifact retention;
- queue leases, deduplication, and multi-machine coordination;
- unattended scheduling, watchdogs, and recovery receipts;
- browser/CDP automation and automatic challenge solving;
- observability, replay, and manual-review handoff.

Current database model names such as `FapaiSeedItem` are legacy storage debt.
They may be adapted behind repository interfaces, but must not leak into new
generic collection contracts. Renaming them requires a separate reversible data
migration with compatibility and rollback proof.

## Live safety boundary

Repository refactoring never authorizes deployment. PC2 and NAS live services
remain immutable unless the user explicitly requests that exact deployment or
runtime action. All normal validation is repository-local and offline.

## File-size governance

Crow adopts the Neuro Hook/Loom effective-line policy:

- target around 150 effective lines;
- 100-250 preferred;
- 251-500 acceptable for one responsibility;
- 501-700 only with a current independent exception;
- 701-1500 must be split before changed work is complete;
- above 1500 has no waiver.

The ratchet baseline records existing debt without legitimizing it. New,
moved, or modified files must meet the current limits. Run:

```powershell
node --test scripts/tests/effective-code-lines.test.mjs
node scripts/effective-code-lines.mjs --mode ratchet --json artifacts/effective-code-lines.json
```

Split along the stage, domain-policy, persistence, I/O, orchestration, and test
fixture boundaries above. Never game the limit through minification, broad
exclusions, or removal of useful tests.

The unified Tampermonkey install file is a deterministic compatibility artifact:
its numbered maintained fragments live under
`tampermonkey_scripts/src/fapaifang_unified/`, while
`scripts/build-userscript.mjs` proves that they reproduce the tracked one-file
output exactly. Do not edit the generated install file directly or replace its
shared IIFE with runtime `@require` dependencies.
