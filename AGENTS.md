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
