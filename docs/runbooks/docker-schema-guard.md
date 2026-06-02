# Docker DB schema guard

The Docker entrypoint runs a read-only database schema guard before starting seed,
detail, API, or legacy collection workers.

## What it checks

When `FAPAI_DB_URL` is set and `FAPAI_DB_SCHEMA_GUARD` is not disabled, the
entrypoint compares:

- the live database tables and columns, inspected through SQLAlchemy; and
- the current SQLAlchemy model metadata from `src/storage/models.py`.

If the database already contains any current application table but is missing a
required table or column, the entrypoint exits with status `1` before launching a
worker subprocess.

Example failure:

```text
[docker-entrypoint] startup check failed: database schema is not compatible with current application models.
Run database migrations before starting workers, for example: python -m alembic upgrade head
```

This is a fail-fast protection for long-running collectors. In particular, it
prevents the detail worker from spending browser and LLM work before failing on a
late database write because the live DB is still on an older schema.

## Empty databases

Completely empty databases are allowed through the guard. This preserves the
existing `FAPAI_DB_AUTO_CREATE=1` first-run path.

Once any current application table exists, the database must match the current
model table/column set before workers start.

## Migration command

For local host-side migrations, use the host-visible PostgreSQL port:

```powershell
$env:FAPAI_DB_URL = "postgresql+psycopg://fapaifang:fapaifang@127.0.0.1:55432/fapaifang"
.\venv\Scripts\python.exe -m pip install -r requirements.txt -r tools\requirements-postgres.txt
.\venv\Scripts\python.exe -m alembic upgrade head
```

Inside Docker, `docker.local.env` can keep using `host.docker.internal`:

```env
FAPAI_DB_URL=postgresql+psycopg://fapaifang:fapaifang@host.docker.internal:55432/fapaifang
```

## Temporary bypass

Only use this for short troubleshooting windows:

```env
FAPAI_DB_SCHEMA_GUARD=0
```

Disabling the guard does not fix the database. It only allows workers to start
and leaves them exposed to later DB write failures.

## Read-only preflight

From the host:

```powershell
@'
import os
from tools.docker_entrypoint import guard_database_schema

os.environ["FAPAI_DB_URL"] = "postgresql+psycopg://fapaifang:fapaifang@127.0.0.1:55432/fapaifang"
guard_database_schema(os.environ)
print("schema_guard=passed")
'@ | .\venv\Scripts\python.exe -
```

From the collector image, without starting a long-running worker:

```powershell
docker compose --env-file docker.local.env -f docker-compose.collection.yml run --rm --no-deps `
  -e FAPAI_RUN_MODE=sleep `
  fapaifang-seed-collector `
  python -c "from tools.docker_entrypoint import guard_database_schema; import os; guard_database_schema(os.environ); print('container_schema_guard=passed')"
```
