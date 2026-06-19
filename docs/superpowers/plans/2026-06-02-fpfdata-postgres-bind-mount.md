# Superseded: FPFData PostgreSQL Bind Mount Implementation Plan

> Superseded on 2026-06-02 after live bind-smoke testing. Do **not** execute the
> migration steps below against `Z:\project\project\FPFData\postgres\data`.
> `Z:` bind mounts on this Docker Desktop setup can mount a stale/internal ext4
> view: container writes succeed but do not appear in the host `Z:` directory,
> and newly created host subdirectories may not be visible to Docker. The safe
> current contract is: keep live PostgreSQL on the Docker named volume
> `fapaifang_postgres_data`; use `FPFData\postgres\backups` only for pg_dump
> backups unless a future target path passes a two-way bind smoke.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the live FapaiFang PostgreSQL data directory from the Docker named volume to `Z:\project\project\FPFData\postgres\data` without losing the current database.

**Architecture:** Make `FAPAI_DATA_ROOT_HOST` the canonical runtime data root for PostgreSQL by default. Preserve data by dumping the current named-volume database, restarting Postgres with a bind mount, restoring the dump, and verifying mount type plus database contents before restarting workers.

**Tech Stack:** Docker Compose, PostGIS PostgreSQL 16, PowerShell, pg_dump/pg_restore, pytest.

---

### Task 1: Lock the compose contract in tests

**Files:**
- Modify: `tools/test/test_docker_entrypoint.py`

- [ ] **Step 1: Replace the default Postgres volume assertion**

Change `test_default_compose_uses_docker_volumes_for_verified_persistent_state` so it still checks collector Docker volumes but requires `docker-compose.postgres.yml` to bind `${FAPAI_DATA_ROOT_HOST}/postgres/data` to `/var/lib/postgresql/data`.

- [ ] **Step 2: Run the targeted test and confirm RED**

Run:

```powershell
$env:PYTHONPATH = (Get-Location).Path
python -m pytest tools/test/test_docker_entrypoint.py::test_default_compose_uses_docker_volumes_for_verified_persistent_state -q
```

Expected: FAIL because `docker-compose.postgres.yml` still uses `postgres_data:/var/lib/postgresql/data`.

### Task 2: Change default Postgres persistence to FPFData bind mount

**Files:**
- Modify: `docker-compose.postgres.yml`
- Modify: `docker-compose.postgres.host-bind.yml`
- Modify: `README.md`
- Modify: `docs/runbooks/docker-schema-guard.md`
- Modify: `scripts/sync-docker-data-to-host.ps1`

- [ ] **Step 1: Update `docker-compose.postgres.yml`**

Replace the `postgres_data` named volume mount with:

```yaml
    volumes:
      - type: bind
        source: ${FAPAI_DATA_ROOT_HOST:?set FAPAI_DATA_ROOT_HOST}/postgres/data
        target: /var/lib/postgresql/data
```

Remove the unused root `volumes: postgres_data:` block.

- [ ] **Step 2: Neutralize the old Postgres host-bind override**

Change `docker-compose.postgres.host-bind.yml` into a compatibility no-op comment file so old commands that include it do not override the same mount twice.

- [ ] **Step 3: Update docs**

Rewrite the persistence section in `README.md` and add a note in `docs/runbooks/docker-schema-guard.md` that live PostgreSQL now defaults to `FAPAI_DATA_ROOT_HOST\postgres`.

- [ ] **Step 4: Update sync script messaging**

Keep `scripts/sync-docker-data-to-host.ps1` able to export dumps, but make the final output say it synced collector volumes and wrote a PostgreSQL backup when not skipped, rather than implying the backup path is the live data root.

- [ ] **Step 5: Run targeted tests and confirm GREEN**

Run:

```powershell
$env:PYTHONPATH = (Get-Location).Path
python -m pytest tools/test/test_docker_entrypoint.py tools/test/test_sync_docker_data_script.py tools/test/test_register_sync_task_script.py -q
```

Expected: PASS.

### Task 3: Dump the current live database before stopping services

**Runtime state:**
- Current DB container: `fapaifang-postgres`
- Current DB volume: `fapaifang_postgres_data`
- Destination data root: `Z:\project\project\FPFData`
- Live PGDATA directory: `Z:\project\project\FPFData\postgres\data`
- Dump backup directory: `Z:\project\project\FPFData\postgres\backups`

- [ ] **Step 1: Record key table counts**

Run SQL against the current running container and save the JSON/text output under `Z:\project\project\FPFData\postgres\backups`.

- [ ] **Step 2: Create a custom-format dump**

Run `pg_dump -Fc` inside `fapaifang-postgres`, copy the dump to `Z:\project\project\FPFData\postgres\backups`, and remove the temporary file from the container.

- [ ] **Step 3: Verify backup exists and is non-empty**

Check file size on the copied dump before stopping services.

### Task 4: Switch Postgres to the bind mount

**Runtime services:**
- Stop before migration: `fapaifang-seed-collector`, `fapaifang-detail-worker`, `fapaifang-postgres`
- Restart after restore: `fapaifang-postgres`, then the workers

- [ ] **Step 1: Stop writer services**

Stop `fapaifang-seed-collector` and `fapaifang-detail-worker`.

- [ ] **Step 2: Stop Postgres**

Stop `fapaifang-postgres`.

- [ ] **Step 3: Prepare `Z:\project\project\FPFData\postgres\data`**

Create a clean `postgres\data` directory for PGDATA and keep existing dumps under `postgres\backups`. If `postgres\data` exists and is not an initialized PostgreSQL data directory, rename only `postgres\data` to a timestamped backup before creating a clean directory.

- [ ] **Step 4: Start Postgres using the updated compose**

Run:

```powershell
docker compose --env-file docker.local.env -f docker-compose.postgres.yml up -d postgres
```

- [ ] **Step 5: Wait for health**

Poll `docker inspect fapaifang-postgres` until health is `healthy`.

### Task 5: Restore and verify

- [ ] **Step 1: Restore the dump**

Copy the dump into the bind-mounted Postgres container and run:

```powershell
docker exec fapaifang-postgres pg_restore -U fapaifang -d fapaifang --clean --if-exists /tmp/<dump-name>
```

- [ ] **Step 2: Verify the mount**

Run `docker inspect fapaifang-postgres` and confirm:

```text
Type: bind
Source: Z:\project\project\FPFData\postgres\data
Destination: /var/lib/postgresql/data
```

- [ ] **Step 3: Verify schema and row counts**

Run `\dt` and key table counts, comparing the post-restore counts to the pre-migration snapshot.

- [ ] **Step 4: Restart workers**

Start `fapaifang-seed-collector` and `fapaifang-detail-worker`.

- [ ] **Step 5: Commit code/docs changes**

Stage only compose/docs/test/script files and commit with:

```powershell
git commit -m "Use FPFData bind mount for Postgres"
```
