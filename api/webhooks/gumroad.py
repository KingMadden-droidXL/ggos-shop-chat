"""Gumroad purchase webhook -> ascension.OS.

Gumroad sends sale webhooks as form-encoded POSTs (sale_id, email,
product_name, price, ...). Gumroad does NOT sign its webhooks, so
anyone who knows this URL can POST a fake purchase. That is why this
endpoint NEVER sends anything: it only runs the ascension router and
queues the pitch for human approval. A fake purchase can at most
create a draft in the approval queue.

Deploy note: mount alongside the Apollo webhook app (one api/index.py
serving both) — not built yet. No Gumroad product, Shield app, or
Vercel project exists to deploy to.
"""
from fastapi import FastAPI, Request

from api.webhooks.event_log import log_event
from services.ascension import on_compliance_shield_purchase

app = FastAPI()


@app.post("/api/webhooks/gumroad")
async def gumroad_webhook_handler(request: Request):
    form = await request.form()
    data = dict(form)
    # Gumroad sale fields: sale_id, email, product_name, price, ...
    # No title/org data arrives, so the buyer scores low and routes
    # WARM (retainer pitch) unless enriched later.
    contact = {
        "id": data.get("sale_id") or data.get("email"),
        "email": data.get("email"),
        "first_name": data.get("first_name"),
        "name": data.get("full_name") or data.get("email"),
        "title": None,
        "city": None,
        "organization": {},
    }
    queued = on_compliance_shield_purchase(contact)
    # WRITE TO THE CONTROL PLANE - sale + queued pitch land in
    # gangster_god.db. The pitch is AWAITING_APPROVAL: nothing is sent
    # from here, a human approves it first.
    log_event(
        "compliance_shield_purchased",
        "gumroad",
        data,
        external_id=data.get("sale_id"),
    )
    log_event(
        "ascension_pitch_queued",
        "ascension.OS",
        queued,
        external_id=data.get("sale_id"),
    )
    return {"ok": True, "queued": queued}
