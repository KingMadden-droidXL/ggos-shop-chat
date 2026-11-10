# GGOS Shop Chat — $0 store assistant

Working code, real answers, $0. No LLM, no model key, no monthly fee.
The chat answers only from the live-store knowledge file plus a short
verified FAQ. Anything else hands off to Gavin.

## Files

- `snippet.liquid` — the theme snippet. Source of truth for the store.
  Paste it into `theme.liquid` just before `</body>`.
- `demo.html` — a copy of the snippet on a fake storefront, for local
  testing only. Regenerate it from `snippet.liquid` if the snippet changes.
- `../ggos/shop_chat.py` — the answer engine (deterministic, no network).
- `../data/shop_knowledge.json` — the live listings it answers from.
- `../scripts/refresh_shop_knowledge.py` — rebuilds the knowledge file
  from the live store. Run it whenever listings change.
- `../render.yaml` — free Render hosting (see below).

## What it answers

Prices, sizes and links for every live listing; STAYCOLD10 (10% off);
shipping (made to order, pressed and shipped by the founder from Hobbs);
the $17 ebook, $37 Master Key, $27 Cashflow guide; store open or not;
how to reach Gavin. Unknown questions get a handoff, never an invented
answer. The hidden AI Money Duo is never mentioned. The contested
Heartless 575 tee gets a "check with Gavin" note, never a buy push.

## Test locally

```bash
cd ~/workspace/ggos-repair
GGOS_CORS_ORIGINS=http://localhost:8080 .venv/bin/python -m uvicorn ggos.app:app --port 8000
# in another shell:
cd shop-chat && python3 -m http.server 8080
# open http://localhost:8080/demo.html, click "Chat with us"
```

## Host it free (Render)

1. Push this repo to GitHub (public or private).
2. In Render, New > Web Service > pick the repo. It reads `render.yaml`:
   free tier, `GGOS_CORS_ORIGINS` already set to the store origin.
3. Deploy, copy the service URL (https://ggos-shop-chat.onrender.com).
4. In `snippet.liquid`, set `GGOS_CHAT_URL` to that URL + `/shop/chat`.
5. Paste the snippet into `theme.liquid` before `</body>`, save.

No secrets needed: `/shop/chat` is public by design and holds no token.
The other GGOS endpoints stay locked behind `GGOS_API_TOKEN` as before.

## Honest limits

- Free Render sleeps after ~15 minutes idle. The first visitor after a
  sleep waits ~30-60 seconds while it wakes. Paid hosting fixes that;
  free does not.
- Answers go stale when listings change. Re-run
  `scripts/refresh_shop_knowledge.py` (or ask Muse) after any price,
  product or status change, then redeploy.
- It cannot look up orders, take payments, or promise delivery dates.
  Order questions hand off to gavinmadden52@gmail.com.
- Rate limit is light (20 messages a minute per visitor) — it stops
  casual floods, not a determined attack. Nothing of value is exposed.
