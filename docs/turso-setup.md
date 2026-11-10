# Turso setup — cloud DB for the Vercel webhook

Goal: one database both sides read — the Vercel webhook writes Apollo /
Gumroad events to it, the local swarm reads the same rows. Local SQLite
keeps working when these env vars are NOT set.

**Free tier (checked Nov 3, 2026, against Turso's pricing page):**
$0, 100 databases, 5 GB storage, 500M rows read/mo, 10M writes/mo,
no credit card. If a quota is hit, queries fail with BLOCKED until you
upgrade — nothing silently bills.

## What is already done in this repo

- `ggos/database.py` branches on env: `TURSO_DATABASE_URL` set → libsql
  client to Turso; unset → local sqlite3 as before. Same schema, same
  functions (`init_db`, `insert_event`, `recent_events`, ...).
- `data/schema.sql` is generated from the repo's own migrations
  (regenerate with `python -m scripts.dump_schema`).
- The libsql path is tested against a local file (`tests/test_turso.py`).
  **The remote Turso path is UNTESTED** — no credentials exist yet. The
  first run against the real Turso DB is the verification step; run it
  and check the rows land before pointing any webhook at it.

## What only Gavin can do (his login)

The Turso account + database live under his login. I can't create them
from here — the CLI login is interactive (GitHub) and the token is his
secret. Steps, in a terminal:

```bash
# 1. Install the CLI (check turso.tech for the current installer)
curl -sSfL https://get.tur.so/install.sh | bash

# 2. Log in (interactive — GitHub)
turso auth login

# 3. Create the database
turso db create gangster-god

# 4. Load the schema (this repo's migrations, generated — see above)
turso db shell gangster-god < data/schema.sql

# 5. Get the URL + a token
turso db show gangster-god --url
turso db tokens create gangster-god
```

## Wiring it up

Local swarm (this machine) — add to `.env` (never commit it):

```bash
TURSO_DATABASE_URL="libsql://gangster-god-....turso.io"
TURSO_AUTH_TOKEN="eyJ..."
```

Unset both to go back to local `data/gangster_god.db`.

Vercel webhook — once the webhook app exists there (no Vercel project
yet):

```bash
vercel env add TURSO_DATABASE_URL
vercel env add TURSO_AUTH_TOKEN
```

Then verify before trusting it: run one webhook delivery and check the
row is in Turso (`turso db shell gangster-god "SELECT * FROM events
ORDER BY id DESC LIMIT 5;"`). Until that check passes, the remote path
is unproven.

## Notes

- The webhook code (`api/webhooks/`) is FastAPI, not the Next.js
  `route.ts` from the paste — the Next.js app doesn't exist, and the
  pasted route never actually wrote to the DB (JSONL + console.log).
  Deploying the FastAPI app to Vercel needs an `api/index.py`
  entrypoint — not built yet, because there is no Vercel project.
- Turso counts rows *scanned*, not rows returned. The events table has
  indexes on `(event_type, timestamp)` and `(source, external_id)`, so
  the webhook's lookups stay cheap. Don't run unindexed `SELECT *`
  scans against it.
- Keep the token out of chat, memory, and files. It goes in `.env`
  and Vercel env only.
