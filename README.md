# GGOS Core — Repaired

A minimal, runnable, auditable core rebuilt from the 2026-09-26 Termux paste.
Every defect in the audit (`your_files/ggos-paste-audit.md`) is fixed or
explicitly removed. No mocks, no theater, no default secrets.

## What changed

| Before | After |
|---|---|
| `server.app` failed importing `BossAgent`; `db_path=` kwarg didn't exist | One `BossAgent(name, db_path)` signature, used everywhere |
| Two competing schemas + relative `./gangster_god.db` paths | One schema module (`ggos/database.py`), one absolute path via `GGOS_DB_PATH`, migration tracking in `schema_version` |
| `get_agent_runs()` SQL broken 3 ways | Fixed: proper `WHERE`, correct params, table exists |
| Hardcoded webhook secret, open trigger endpoint, CORS `*` + credentials | Bearer-token auth on trigger endpoints; 503 when no token configured; CORS only for listed origins |
| "Market signals" = random numbers; transformer = canned copy; license = theater | Removed. The two future-AI hooks exist as explicit `NotImplementedError` stubs |
| Fake $25k trade payload, no approval gates | `ggos/notifier.py`: outbound disabled unless `GGOS_OUTBOUND_ENABLED=1` **and** `approved=True` per call |
| Money inserts with no dedup | `transaction_exists(source, external_id)` before every insert; `UNIQUE(source, external_id)`; integer cents |
| Money engine rules | Still sync-only (`sqlite3`, no async, no network) |

## Quickstart

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# run the tests (stdlib only, no network, no real money)
.venv/bin/python -m unittest discover -s tests -v

# boot the API (DB auto-initializes on startup)
GGOS_API_TOKEN="$(openssl rand -hex 32)" \
  .venv/bin/python -m uvicorn ggos.app:app --port 8000

curl localhost:8000/api/v1/health   # no auth — wait, this build uses /health
```

Endpoints (all except `/health` need `Authorization: Bearer <token>`):

- `GET /health` — liveness + schema version
- `POST /swarm/trigger` — runs one real agent cycle (verify → plan → execute)
- `GET /events`, `GET /agent-runs`
- `POST /money/record` — `{"source","external_id","amount_cents","direction":"in|out"}`
- `GET /money/balance`, `GET /money/transactions`
- `POST /tasks`, `GET /tasks`, `GET /tasks/{id}`, `PATCH /tasks/{id}` — real work queue (`pending` → `in_progress` → `completed`/`failed`)
- `POST /sops`, `GET /sops` — standard operating procedures keyed by trigger event
- `POST /prompt-runs`, `GET /prompt-runs` — records real pipeline inputs/outputs; generates nothing

## Environment

| Var | Default | Notes |
|---|---|---|
| `GGOS_DB_PATH` | `<project>/data/gangster_god.db` | single absolute path |
| `GGOS_API_TOKEN` | _(empty)_ | empty = trigger endpoints answer 503 |
| `GGOS_CORS_ORIGINS` | _(empty)_ | comma-separated; empty = CORS off |
| `GGOS_OUTBOUND_ENABLED` | `0` | must be `1` **and** per-call `approved=True` |
| `SHOPIFY_SHOP_DOMAIN` | _(empty)_ | e.g. `w1q4is-1q.myshopify.com` — the store the client reads |
| `SHOPIFY_ADMIN_TOKEN` | _(empty)_ | shpat_ Admin API token — env only, never in code, never in chat |
| `GGOS_SHOPIFY_WRITE_ENABLED` | `0` | must be `1` **and** per-call `approved=True` for any Shopify write |

See `.env.example`.

## Termux notes (your phone)

- `numpy`/`pandas` wheel builds fail on Termux — this core doesn't need them.
- `pkg install python`, then the venv steps above work as-is.
- **Purge the leaked secrets from the old session first:**
  ```bash
  history -c && history -w   # wipe shell history
  rm -f ~/.bash_history
  grep -rl 'MASTER_KEY\|WEBHOOK_SECRET' ~/ggos 2>/dev/null  # find files holding them
  ```
  Then rotate anything that appeared in that transcript — treat it as public.

## 36 agents (`ggos/agents.py`)

36 distinct, report-only agents in registry order (Analyst, CatalogAgent,
CreativeDirector, ManufacturingLead, GrowthMarketer first, SwarmCommander
last). Each computes from a store-context JSON snapshot it is given —
no network, no Shopify client, no posts/DMs/emails, no spending, no
invented specs. `run_swarm()` returns one change package that is always
`approved=False, applied=False`; `apply_package()` raises unless
approved, and even then raises `NotImplementedError`, because the push
happens in chat with Muse after the owner approves the exact changes.

```bash
.venv/bin/python -m ggos.agents --context data/store_context_oct28.json --out data/swarm-report-oct28.json
# Agents run: 36, Proposed changes (draft only): 6, Blocked: 13, Needs owner: 20
# On the Oct 28 first-page snapshot (20 of 23 products): 4 duplicate
# Wave 2 pairs, 10 image-less products, 4 empty Teddy descriptions,
# Wave 2 tee floor $29.99 vs live $26.99 in that page.
```

## Shopify, stood alone — god mode, as far as it goes

Velvet over concrete. GGOS talks straight to Shopify's Admin API now,
no Replit in the middle, no WealthArchitectBot in the middle:
`integrations/shopify/shopify_client.py`. Reads are the whole house —
shop, products, orders, counts. Writes have two locks, both at once,
or nothing moves: `GGOS_SHOPIFY_WRITE_ENABLED=1` **and** `approved=True`
on that exact call. A write that gets through is created as a draft
only; it never publishes live on its own.

God mode is `services/shopify_godmode.py` — one command, total sight:

```bash
SHOPIFY_SHOP_DOMAIN=w1q4is-1q.myshopify.com SHOPIFY_ADMIN_TOKEN=shpat_... \
  python -m services.shopify_godmode
# Reads the live store, runs all 36 agents over it, writes the receipt
# to data/shopify-godmode-report.json. Change package is ALWAYS
# approved=False, applied=False. Sight, not action.
```

That is the ceiling, by design. The push still happens in chat with
Muse, after the owner approves the exact changes. Love is a liability.
Style is armor. Receipts for every job.

## What's intentionally NOT here

Market intelligence, content transformation, license enforcement,
self-evolution. Those were faked in the paste; faking them again would just
be prettier theater. They are explicit `NotImplementedError` stubs in
`ggos/boss.py` until real implementations exist. `ggos/intelligence.py`
is the one exception, and only for observation: it reads real 24h price
charts from CoinGecko's public API, scores the moves, and persists every
result as unapproved `HOLD`. `ggos/paper_tracker.py` (schema v3) records
each live scan and judges it later against a real price — no trades, no
money, and no edge claimed before 30 evaluated predictions. There is no
exchange connection, wallet, capital, or backtested edge here. God mode
stops at the gates on purpose: no auto-publish, no auto-send, no spend.
