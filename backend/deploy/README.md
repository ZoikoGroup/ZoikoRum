# Database for a new Zoikorum environment

There are two ways to create the database. Both give the same result: every table, the starter specialization list,
and nothing else. There are no accounts, passwords, customer data or demo data.

## Recommended: migrations

The normal way, used for every later release as well:

```
docker compose -f docker-compose.prod.yml run --rm migrate      # = alembic upgrade head
```

## Alternative: `zoikorum_fresh_install.sql`

This is a snapshot of a freshly migrated, empty database (PostgreSQL 16, migration `f2324ef9bd82`). It contains
91 tables in 22 schemas, the triggers that keep audit and ledger records append-only, the 133 starter
specializations, and the migration marker.

1. Create an empty database and the user the app connects as.
2. Load the file with **psql 16.10 or newer**. The file starts with a `\restrict` line that older psql versions do
   not understand.

   ```
   psql "postgresql://<user>:<password>@<host>:5432/<database>" -v ON_ERROR_STOP=1 -f zoikorum_fresh_install.sql
   ```

3. Give the app's database user rights on all the schemas and tables. The file has no owners or grants, so it
   works with any user name.
4. Run `alembic upgrade head` once. It should report nothing to do. After that, every release adds its changes
   through migrations.

The snapshot only matches the migration it was made from. Regenerate it whenever the database changes:
`pg_dump --no-owner --no-privileges --exclude-table-data=platform.timers` of a freshly migrated database.
Never share a dump of a database that has been used (development, demo or production). Those contain personal data
and password hashes.

After the database is ready, create the first staff account with
`python -m zoikorum.cli create-admin --email <admin email>`. The password is asked for, or read from
`ZK_ADMIN_PASSWORD`.
