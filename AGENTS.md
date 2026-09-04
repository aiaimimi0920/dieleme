# Repository operating rules

## Live systems are immutable by default

- Never deploy, synchronize, restart, stop, reconfigure, or hot-patch the
  running PC2 or NAS services unless the user explicitly requests that exact
  live action in the current conversation.
- Do not run deployment, rollback, watchdog-registration, worker-launch,
  Docker/Compose mutation, remote copy, SSH mutation, or process-control
  commands against PC2 or NAS as part of ordinary development or validation.
- Source changes do not authorize deployment. Validate them with offline unit
  tests, syntax checks, builds, and repository-local fixtures only.
- Read-only inspection must not be presented as a deployment or runtime
  verification.

## Project paths and runtime data

- Derive project paths from the repository root; do not hard-code the checkout
  name, drive letter, UNC share, or developer home directory.
- The default project-local runtime-data root is `FPFData/`. Environment or
  command-line overrides remain supported for existing installations.
- `FPFData/` may contain credentials, browser profiles, database backups, and
  large generated artifacts. Its runtime contents must remain outside Git;
  only its management documentation and ignore policy are versioned.

## Crow engine boundaries

- Crow is organized into three product engines: collection, data analysis, and
  prediction. Only the collection engine is currently mature enough to be
  treated as an implemented product capability.
- The collection engine has three explicit stages: rough discovery of source
  links, detail-page capture, and evidence-based AI archiving. Source-specific
  field names and completion rules belong in `src/collection/adapters/`, not in
  source-neutral orchestration.
- Storage, multi-machine coordination, unattended operation, and automatic
  challenge solving are cross-cutting collection runtime capabilities. They are
  not separate product engines and must not bypass the live-system rules above.
- Do not present the current analysis or prediction code as complete. Existing
  AVM and analysis modules are migration inputs until their contracts and
  release gates are explicitly completed.

## Effective-code-line and splitting policy

- Effective lines exclude blank lines, comment-only lines, and documentation
  blocks. Inline comments on executable lines still count. The language-aware
  checker is authoritative.
- Target about 150 effective lines per file. 100-250 is preferred; 251-500 is
  acceptable for one cohesive responsibility; 501-700 requires a current,
  independently reviewed exception; 701-1500 is unacceptable for completed
  new or changed work; more than 1500 has no waiver.
- Existing oversized files recorded in the baseline may remain only while
  source-content unchanged; line-ending and UTF-8 BOM normalization do not
  count as code changes. A changed oversized file must be split to at most 700
  effective lines, with a target of at most 500.
- Split by responsibility: domain policy and serialization, parsing and
  validation, business state, I/O and persistence, runtime orchestration, UI,
  and test fixtures. Do not split at arbitrary line numbers or create a giant
  `utils`/`common` dumping ground.
- Never satisfy the checker by deleting useful tests, excluding product source,
  minifying code, or moving logic into generated/runtime-data directories.
- Required local gates for relevant changes:
  - `node --test scripts/tests/effective-code-lines.test.mjs`
  - `node scripts/effective-code-lines.mjs --mode ratchet --json artifacts/effective-code-lines.json`
  - focused tests, formatter/type checks, and `git diff`/`git status` review.
- Use `--mode strict` only as a migration report until all grandfathered debt is
  removed. Baseline or policy regeneration requires explicit review of the
  recorded source commit, exclusions, hashes, and oversized-file inventory.
