"""Shop chat: the $0 GGOS shop assistant.

No LLM, no network, no money. Answers come only from the live-store
knowledge file (data/shop_knowledge.json, refreshed from Shopify by
scripts/refresh_shop_knowledge.py) and the small verified FAQ list below.
Anything it cannot answer from those two sources gets a handoff to Gavin
instead of an invented answer.

Rules, hard:
- Never mention a product that is not in the knowledge file (drafts,
  archived and hidden items do not exist to this chat).
- Never state order counts, sales numbers, reviews or delivery promises.
- The AI Money Duo ($47) is hidden on purpose and is never mentioned.
- The contested Heartless 575 tee is answered with a check-with-Gavin
  note, never a buy push.
"""
import json
import re
import time
from pathlib import Path

from . import config

KNOWLEDGE_PATH = config.DATA_DIR / "shop_knowledge.json"

CONTACT = {
    "email": "gavinmadden52@gmail.com",
    "instagram": "@noloveappeal187",
    "tiktok": "@gavinmfmadden",
    "phone": "(575) 300-3613",
}

STORE_URL = "https://noloveappeal575.myshopify.com"

# Verified facts only. No prices here except the live discount code and
# the three digital guides, which are also in the knowledge file.
DISCOUNT_CODE = "STAYCOLD10"  # 10% off, live
SHIPPING_REPLY = (
    "Everything is made to order — pressed and shipped by the founder "
    "from Hobbs, NM. No warehouse, no middleman. Usually allow 5-9 "
    "business days to press, plus 4-6 business days standard shipping. "
    "Your exact delivery date shows at checkout."
)
GUIDES_REPLY = (
    "The guides are instant downloads after checkout: the AI Master Key "
    "Blueprint is $37, AI Cashflow Systems 2026 is $27, and the story "
    "ebook \"No Love. Still Here.\" is $17 (14 pages). Real work, real "
    "price, real delivery."
)
CONTACT_REPLY = (
    "You can reach Gavin at gavinmadden52@gmail.com, on Instagram "
    "@noloveappeal187, TikTok @gavinmfmadden, or (575) 300-3613."
)
FALLBACK_REPLY = (
    "I don't know that one — I only answer from what's live in the store. "
    + CONTACT_REPLY
)

_STOPWORDS = {
    "the", "a", "an", "is", "it", "its", "do", "does", "did", "can", "could",
    "i", "me", "my", "you", "your", "we", "how", "much", "many", "what",
    "whats", "what's", "when", "where", "which", "who", "buy", "get", "got",
    "have", "has", "had", "for", "to", "of", "in", "on", "and", "or", "with",
    "that", "this", "there", "here", "are", "am", "be", "please", "want",
    "need", "look", "looking", "show", "tell", "about", "any", "some", "one",
    "cost", "price", "priced", "size", "sizes", "available", "stock",
    "order", "orders", "shipping", "ship", "delivery", "deliver",
}

# Simple per-key rate limit: 20 requests a minute. This is abuse-light,
# not abuse-proof — the endpoint holds no secrets and moves no money.
_RATE_LIMIT = 20
_RATE_WINDOW = 60.0
_hits: dict = {}


def check_rate_limit(key: str) -> bool:
    """True when the caller may proceed, False when over the limit."""
    now = time.monotonic()
    window = _hits.setdefault(key, [])
    window[:] = [t for t in window if now - t < _RATE_WINDOW]
    if len(window) >= _RATE_LIMIT:
        return False
    window.append(now)
    return True


def load_knowledge() -> dict:
    try:
        return json.loads(KNOWLEDGE_PATH.read_text())
    except (OSError, ValueError):
        return {"products": []}


def _words(text: str) -> set:
    return set(re.findall(r"[a-z0-9]+", text.lower())) - _STOPWORDS


def _title_words(title: str) -> set:
    return set(re.findall(r"[a-z0-9]+", title.lower()))


def match_products(message: str, products: list) -> list:
    """Rank products by title-word overlap. Returns [(score, product)]."""
    msg_words = _words(message)
    if not msg_words:
        return []
    ranked = []
    for product in products:
        title_words = _title_words(product["title"])
        overlap = msg_words & title_words
        if not overlap:
            continue
        score = len(overlap)
        # A full title phrase in the message is a strong signal.
        if product["title"].lower() in message.lower():
            score += 3
        ranked.append((score, product))
    ranked.sort(key=lambda item: (-item[0], item[1]["title"].lower()))
    return ranked


def _product_reply(product: dict) -> dict:
    sizes = product.get("sizes") or []
    size_text = f" Sizes {', '.join(sizes)}." if sizes else ""
    link = {"label": product["title"], "url": product["url"]}
    if product.get("contested"):
        return {
            "reply": (
                f"The {product['title']} is ${product['price']}.{size_text} "
                "Heads up — this design is being reworked right now, so "
                "message Gavin before ordering to confirm what you will get. "
                + CONTACT_REPLY
            ),
            "links": [link],
            "handoff": True,
        }
    return {
        "reply": (
            f"The {product['title']} is ${product['price']}.{size_text} "
            "Made to order, pressed and shipped by the founder."
        ),
        "links": [link],
        "handoff": False,
    }


def answer(message: str) -> dict:
    """Answer one visitor message. Returns reply/links/handoff."""
    text = (message or "")[:500]
    lowered = text.lower()
    msg_words = _words(text)
    products = load_knowledge().get("products", [])

    if not text.strip():
        return {
            "reply": (
                "Hey — ask me about anything live in the store: prices, "
                "sizes, shipping, the discount code, the book or the guides."
            ),
            "links": [],
            "handoff": False,
        }

    if not products:
        return {"reply": FALLBACK_REPLY, "links": [], "handoff": True}

    # Intents that do not need a product match.
    if re.search(r"\b(hi|hello|hey|yo|sup)\b", lowered) and len(msg_words) <= 2:
        return {
            "reply": (
                "Hey, welcome to NoLoveAppeal. Ask me about a product, "
                "sizes, shipping, the discount code, the book or the guides."
            ),
            "links": [],
            "handoff": False,
        }
    if ("staycold" in lowered or "discount" in lowered
            or re.search(r"\b(code|coupon|off)\b", lowered)):
        return {
            "reply": (
                f"{DISCOUNT_CODE} takes 10% off. Enter it at checkout."
            ),
            "links": [],
            "handoff": False,
        }
    if (re.search(r"\bship\w*\b", lowered) or "deliver" in lowered
            or "arrive" in lowered
            or ("long" in lowered and "take" in lowered)):
        return {"reply": SHIPPING_REPLY, "links": [], "handoff": False}
    if re.search(r"\btrack", lowered) or "where" in lowered and "order" in lowered:
        return {
            "reply": (
                "I can't look up orders — send your order number to "
                + CONTACT_REPLY
            ),
            "links": [],
            "handoff": True,
        }
    if "contact" in lowered or "human" in lowered or "gavin" in lowered \
            or "reach" in lowered or "talk to" in lowered:
        return {"reply": CONTACT_REPLY, "links": [], "handoff": True}
    if "open" in lowered and ("store" in lowered or "shop" in lowered):
        return {
            "reply": (
                "Yes — the store is open and taking orders right now."
            ),
            "links": [],
            "handoff": False,
        }
    if ("book" in lowered or "ebook" in lowered or "guide" in lowered
            or "master key" in lowered or "cashflow" in lowered):
        ranked = match_products(text, products)
        if ranked and ranked[0][0] >= 2:
            return _product_reply(ranked[0][1])
        return {
            "reply": GUIDES_REPLY,
            "links": [
                {"label": "No Love. Still Here. — $17",
                 "url": f"{STORE_URL}/products/no-love-still-here"},
                {"label": "AI Master Key — $37",
                 "url": f"{STORE_URL}/products/ai-master-key-blueprint"},
            ],
            "handoff": False,
        }

    # Product questions: best match wins; near-ties get a short list.
    ranked = match_products(text, products)
    if ranked:
        top_score = ranked[0][0]
        if top_score >= 2:
            return _product_reply(ranked[0][1])
        if top_score == 1 and len(ranked) <= 3:
            lines = ", ".join(
                f"{p['title']} (${p['price']})" for _, p in ranked[:3]
            )
            return {
                "reply": (
                    f"Did you mean one of these? {lines} — tell me which "
                    "one and I will give you the sizes and the link."
                ),
                "links": [
                    {"label": p["title"], "url": p["url"]}
                    for _, p in ranked[:3]
                ],
                "handoff": False,
            }

    return {"reply": FALLBACK_REPLY, "links": [], "handoff": True}
