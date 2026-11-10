# GangsterGodOS gateway wiring — unlock runs the real sweep

## What changed (Nov 7, 2026)

The live gateway page (`workspace/user/files/gangstergodos.html`) is still
the untouched front door: 36 agent names, $99 / $499 / $999, Cash App
`$Manifestingmoney10`, access codes as SHA-256 hashes only. Its unlocked
screen says the live command center is not wired in yet.

The wiring lives in new files next to it:

- `api/godmode.py` — `run_godmode_report()`. Runs one read-only
  `godmode_sweep()` and returns a status envelope. When the Shopify
  token is not in the server env it returns `status: "token_not_set"`,
  `report: null`, `applied: false`, and no numbers at all.
- `ggos/app.py` — new `POST /godmode/sweep`, behind the same bearer
  gate as the other trigger endpoints (`GGOS_API_TOKEN`). 503 when the
  API token is not configured, 401 on a wrong token.
- `gangstergodos-wired.html` — copy of the live page with only the Full
  Access screen changed. Same hashes, prices, Cash App link, and 36
  roster names (checked by test). The unlocked screen has a
  RUN SHOPIFY SWEEP button, an API base URL field (default
  `http://localhost:8000`), and an API token field (typed per run,
  never saved). It shows the real report — shop, product/order counts,
  agents run, proposed-change count, blocked, needs-owner — with
  Approved: False, Applied: False, or the token-not-set state.
- `tests/test_godmode_api.py` — 8 tests: token-not-set states, fake-client
  sweep with receipt, route registration, wired-page invariants, live
  page untouched.

## Gates (unchanged)

Read-only sweep. Draft-only change package, always approved=False and
applied=False. No auto-apply, no send, no spend, no publish, no payment
taken. Shopify token only from env (`SHOPIFY_ADMIN_TOKEN`, fallback
`SHOPIFY_TOKEN`) plus `SHOPIFY_SHOP_DOMAIN`. Never in chat, code, logs,
or a committed file.

## How to run it

From `workspace/ggos-repair`, with the Shopify token in the environment:

```bash
SHOPIFY_SHOP_DOMAIN=w1q4is-1q.myshopify.com \
SHOPIFY_ADMIN_TOKEN=<shpat_ token, env only> \
GGOS_API_TOKEN=<pick a bearer token, env only> \
.venv/bin/python -m uvicorn ggos.app:app --port 8000
```

Then open `gangstergodos-wired.html`, unlock with an access code, type
the same `GGOS_API_TOKEN` into the API token field, and press
RUN SHOPIFY SWEEP. The receipt lands at
`data/shopify-godmode-report.json`.

Without the Shopify token in env the page shows the token-not-set
state and no numbers. That is the expected state until the token is set.

## Taking it live

Swapped Nov 7, 2026 on the owner's "Test it then take it live": the
tests passed (106, OK) after the wired copy's access hashes were
updated to the rotated live-page hashes, and
`workspace/user/files/gangstergodos.html` is now the wired copy.
Backup of the pre-wiring page:
`workspace/user/files/gangstergodos-before-wiring-2026-11-07.html`.
Not yet seen: a live sweep run from the wired page — that still
needs the Shopify token in env and the API server running.
