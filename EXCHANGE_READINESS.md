# Exchange readiness — NOT connected, NO trades

Status on 2026-10-28: no exchange is connected to GGOS. No API key, secret,
password, or seed phrase is stored anywhere in this project. Nothing here
can buy or sell. That is deliberate.

## What Gavin needs to tell Muse (words only, never secrets)

1. Which exchange? Name only, e.g. Coinbase, Kraken, Binance.US.
   Do not paste a login, key, or secret to answer this.
2. Is the account already open, ID-verified, and funded? Yes / no / partly.
3. How much money, in dollars, are you willing to lose completely?
   Trading can lose all of it. There is no safe amount to promise back.
4. Which coins only? (The paper tracker currently watches bitcoin and
   ethereum.)
5. Max dollars per trade, and max loss per day, that you want enforced?

Do NOT send in chat, in a paste, or in a file:
- API keys or API secrets
- Passwords, 2FA codes, or recovery/seed phrases
- Screenshots showing keys or QR codes

If an execution step is ever approved, keys go through Muse's secure
entry flow only, and only after the paper tracker has been judged.

## Rules before any real trade is even discussed

- Paper first: at least 30 evaluated predictions, and the summary must
  be read honestly. Fewer than 30 is not enough to claim an edge.
- Human approval for every trade. No auto-EXECUTE.
- Trade-only API key: trading permission only, withdrawals OFF, and
  the smallest permissions the exchange allows.
- Tiny first size, and fees counted: exchange fees and spread can eat
  a small price move whole.
- One exchange, one account, in Gavin's own name. No shared or
  borrowed accounts, no keys from another AI's paste.
- Stop rule agreed in advance: daily loss limit, and a pause if it hits.

## How the paper tracker runs (no money)

```bash
cd ~/workspace/ggos-repair
.venv/bin/python -m ggos.intelligence --live        # scan + record, 24h horizon
.venv/bin/python -m ggos.intelligence --evaluate-paper   # judge due predictions
.venv/bin/python -m ggos.intelligence --paper-summary    # report only
```

Paper predictions live in the `paper_predictions` table (schema v3).
Evaluated rows record the real later price and the forward return.
Unevaluated rows are never guessed.
