# Deploy the webhook to Vercel (FastAPI, not Next.js)

The webhook that exists is Python/FastAPI (`api/webhooks/apollo.py` +
`api/webhooks/gumroad.py`), tested, with Turso support already in
`ggos/database.py`. There is no Next.js Shield app — the pasted deploy
pack assumed one. This deploys the webhook that actually exists.

## What the pasted pack got wrong (so you don't use it)

- **No route handler in the 4 files.** `package.json` + `.env.example` +
  `schema.sql` + `vercel.json` — none of them is the webhook. The
  "proof" curl (GET) would 404/405 against a POST-only route. The GET
  health endpoint added here (`/api/webhooks/apollo` → `{"status":
  "ok", ...}`) makes the proof curl real.
- **Wrong schema + fake seed rows.** The pasted `scripts/schema.sql`
  defines a different `events` table (5 text columns) than the repo's
  real one (8 columns incl. `external_id`, `data`, `timestamp`) — the
  repo's `insert_event` would fail against it. And it seeds
  `evt_proof_001` / `run_proof_001` "godmode_unlocked" rows — fake
  proof inserted into the DB. Never do that. Use `data/schema.sql`
  (generated from the repo's migrations).
- **Dead `vercel.json` env syntax.** `"env": {"X": "@secret"}` is the
  removed Vercel Secrets feature — those `@` references no longer
  work. Env vars are set with `vercel env add` (below), not in the
  file. No `vercel.json` is needed at all for this project.
- **Invented license.** `GANGSTER_TOKEN=GavinMadden575_Heartless_...
  |2026-04-06_Lifetime_Grant` is a made-up string from the other AI,
  not a real credential. Don't put it in `package.json` or `.env` —
  it buys nothing and it pollutes the config.
- **`GUMROAD_WEBHOOK_SECRET` doesn't exist.** Gumroad doesn't sign
  its webhooks, so there is no secret to set. That's why the Gumroad
  handler only queues pitches for approval instead of auto-acting.

## Prerequisites (all Gavin's)

1. Vercel account + `vercel login` (interactive — your login).
2. Turso DB + token — see `docs/turso-setup.md` (`turso db create
   gangster-god`, schema load, `turso db tokens create gangster-god`).
3. Apollo API key (Settings → API Keys in Apollo) + the two real
   sequence IDs from the Apollo UI (the `SEQ_*` values in the repo
   are placeholders).

## Deploy

From the repo root (`~/workspace/ggos-repair`):

```bash
vercel login
vercel link
vercel env add TURSO_DATABASE_URL
vercel env add TURSO_AUTH_TOKEN
vercel env add APOLLO_API_KEY
vercel env add APOLLO_WEBHOOK_SECRET
vercel --prod
```

Vercel auto-detects Python from `requirements.txt` and serves
`api/webhooks/apollo.py` at `/api/webhooks/apollo` and
`api/webhooks/gumroad.py` at `/api/webhooks/gumroad`. `.vercelignore`
keeps the venv, the local DB, and the tests out of the deployment.

## Verify (before trusting it)

```bash
# 1. Liveness — must return {"status": "ok", ...}
curl -s https://YOUR-APP.vercel.app/api/webhooks/apollo

# 2. Point Apollo's webhook at:
#    https://YOUR-APP.vercel.app/api/webhooks/apollo
#    Point Gumroad's webhook at:
#    https://YOUR-APP.vercel.app/api/webhooks/gumroad

# 3. Send one real event, then check it landed in Turso:
turso db shell gangster-god \
  "SELECT event_type, source FROM events ORDER BY id DESC LIMIT 5;"
```

Until step 3 shows a real row, the deployed webhook is unproven.
Nothing auto-sends from it: Apollo replies log only; a Gumroad
purchase queues the ascension pitch for your approval.
