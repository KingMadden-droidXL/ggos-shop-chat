"""Version manifest for GGOS Core — the one place versions live.

The pasted bridge.py this replaces imported a `swarm_v2` module that does
not exist in this repo (no TaskContract, Supervisor, LLMRouter,
BudgetGovernor, VersionManifest) and a `versions.json` that was never
written, and it built a second Flask server next to the FastAPI app that
already serves /shop/chat, /swarm/trigger and /godmode/sweep.

This module is the real thing: the app version, the DB schema version,
and the minimum client version the trigger endpoints accept.
GET /v1/version serves this envelope. POST /swarm/trigger rejects a
declared client older than the minimum with 426 instead of running it.
Callers that declare no version still run — enforcement starts when a
caller declares one, so the live gateway page keeps working unchanged.
"""
import re

from . import database as db

APP_VERSION = "0.1.0"
MIN_CLIENT_VERSION = "0.1.0"

COMPONENTS = {
    "ggos-core": APP_VERSION,  # FastAPI surface in ggos/app.py
    "shop-chat": APP_VERSION,  # deterministic answers, ggos/shop_chat.py
    "boss-agent": APP_VERSION,  # BossAgent cycle, ggos/boss.py
    "godmode-sweep": APP_VERSION,  # read-only Shopify sweep, api/godmode.py
}


def version_envelope():
    return {
        "app_version": APP_VERSION,
        "schema_version": db.SCHEMA_VERSION,
        "min_client_version": MIN_CLIENT_VERSION,
        "components": dict(COMPONENTS),
    }


def _parse(v):
    parts = []
    for p in str(v).replace("-", ".").replace("+", ".").split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return parts


def _cmp(a, b):
    ap, bp = _parse(a), _parse(b)
    n = max(len(ap), len(bp))
    ap += [0] * (n - len(ap))
    bp += [0] * (n - len(bp))
    for x, y in zip(ap, bp):
        if x != y:
            return -1 if x < y else 1
    return 0


def satisfies(actual, spec):
    """True if version `actual` satisfies a spec like '>=0.1.0 <0.2.0'."""
    for op, ver in re.findall(r"(>=|<=|==|!=|>|<)\s*([\d.\-+]+)", spec or ""):
        c = _cmp(actual, ver)
        ok = {">=": c >= 0, "<=": c <= 0, "==": c == 0,
              "!=": c != 0, ">": c > 0, "<": c < 0}[op]
        if not ok:
            return False
    return True


def client_too_old(declared):
    """None if the declared client version is fine, else a detail string."""
    if declared is None:
        return None
    if not satisfies(declared, ">=" + MIN_CLIENT_VERSION):
        return (
            f"client {declared} is older than minimum {MIN_CLIENT_VERSION}"
        )
    return None
