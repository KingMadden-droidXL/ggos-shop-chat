"""Outbound dispatch lives here and ONLY here.

Disabled by default. Two independent gates must both pass:
  1. GGOS_OUTBOUND_ENABLED=1 in the environment, AND
  2. approved=True passed to the individual call.

Nothing in the money engine, the boss agent, or the API calls this module
without both gates satisfied. There are no default webhooks and no default
secrets anywhere in this project.
"""


class OutboundDisabledError(RuntimeError):
    pass


def dispatch_webhook(url, payload, *, approved=False, timeout=10):
    """POST a JSON payload. Raises OutboundDisabledError unless enabled
    via env AND explicitly approved for this call."""
    import os

    if os.environ.get("GGOS_OUTBOUND_ENABLED", "0") != "1":
        raise OutboundDisabledError(
            "Outbound dispatch is disabled. Set GGOS_OUTBOUND_ENABLED=1 to enable."
        )
    if not approved:
        raise OutboundDisabledError(
            "Outbound dispatch requires approved=True on this call."
        )
    import json
    import urllib.request

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return {"status": resp.status, "url": url}
