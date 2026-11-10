"""Apollo webhook receiver. FastAPI app; mount at /api/webhooks/apollo.

FIXED vs the pasted draft: the draft read the secret and then never
checked anything, so anyone could POST fake replies into the pipeline.
This version actually verifies the signature.

Signature check: if APOLLO_WEBHOOK_SECRET is set, the request MUST
carry a matching HMAC-SHA256 signature or it is rejected (401).

HEADER NAME IS UNVERIFIED — confirm the header Apollo actually sends
in its webhook docs before deploying; the handler reads
X-Apollo-Signature. If Apollo sends no signature at all, leaving the
secret empty lets anything through — only do that behind a trusted
network, never on a public endpoint.

Event bus: REVENUE.OS does not exist yet, so handlers log for now and
return. Wire the follow-up / stop-sequence / create-opportunity steps
when it does. Nothing here sends a message or a checkout link on its
own — that stays behind a human approval.
"""
import hashlib
import hmac
import os

from fastapi import FastAPI, HTTPException, Request

from api.webhooks.event_log import log_event

app = FastAPI()

# CONFIRM against Apollo's webhook docs — unverified.
SIGNATURE_HEADER = "X-Apollo-Signature"


def _signature_valid(body: bytes, signature: str, secret: str) -> bool:
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


@app.get("/api/webhooks/apollo")
async def apollo_webhook_health():
    """Liveness check for the deploy proof curl. Read-only: no DB
    access, no secrets. The real webhook is POST-only."""
    return {
        "status": "ok",
        "service": "apollo-webhook",
        "turso_configured": bool(os.getenv("TURSO_DATABASE_URL")),
    }


@app.post("/api/webhooks/apollo")
async def apollo_webhook_handler(request: Request):
    body = await request.body()
    secret = os.getenv("APOLLO_WEBHOOK_SECRET", "")
    if secret:
        signature = request.headers.get(SIGNATURE_HEADER, "")
        if not _signature_valid(body, signature, secret):
            raise HTTPException(status_code=401, detail="bad webhook signature")

    payload = await request.json()
    event_type = payload.get("type")  # email_opened, email_replied, etc.

    # WRITE TO THE CONTROL PLANE - every Apollo event lands in
    # gangster_god.db (events table). Replies do NOT auto-add anyone
    # to a sequence: follow-up stays behind a human approval.
    log_event(
        event_type or "unknown",
        "apollo",
        payload,
        external_id=payload.get("id"),
    )

    # EVENT BUS -> INTELLIGENCE.OS (log only until REVENUE.OS exists)
    if event_type in ("email_replied", "interested"):
        # -> REVENUE.OS: create opportunity
        # Trigger Execution.OS to stop sequence + notify you
        print(f"HOT REPLY: {payload}")
    elif event_type == "email_bounced":
        # -> mark bad contact
        print(f"BOUNCED: {payload}")
    elif event_type == "meeting_booked":
        # -> ASCENSION.OS - move to closing
        print(f"MEETING BOOKED: {payload}")

    return {"ok": True}
