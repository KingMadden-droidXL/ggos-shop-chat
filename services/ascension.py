"""ascension.OS — the $49 -> $497/mo -> $3,500 stack.

WEDGE: System 4 Compliance Shield ($49 basic / $197 pro) gets the
card + trust. UPSELL: System 1 Local Automation ($1,500 setup +
$497/mo) is the recurring bag. HIGH-TICKET: HOT buyers (score 80+)
get the $3,500 DFY Compliance + Funnel.

FIXED vs the pasted draft:
- The draft's upsell claimed missed calls / no reviews are "actually
  non-compliant too under FTC". That is not true — the FTC polices
  deceptive advertising and disclosures, not whether a shop returns
  calls or has reviews. The pitch below drops that line; the honest
  lever is lost money, not a fake violation.
- The draft called add_to_sequence() without approval, expecting it
  to send. Under the approval gate it returns PENDING_APPROVAL — and
  that is the correct behavior. This module QUEUES the pitch for a
  human approve / reject / edit and never sends on its own.
- Prices are the doc's REPORTED ranges, not guarantees.

NOTE: a bare Gumroad sale carries no firmographic data (no title,
no org size, no tech signal), so the buyer scores low and routes
WARM by default. Routing HOT correctly needs an Apollo enrich by
email first — not built yet.
"""
from kernel.config import ASCENSION_SEQUENCES, ICP_MODES
from services.intelligence import score_prospect_multi

HOT_THRESHOLD = 80


def _person_from_contact(contact):
    org = contact.get("organization") or {}
    return {
        "first_name": contact.get("first_name"),
        "name": contact.get("name"),
        "email": contact.get("email"),
        "title": contact.get("title"),
        "city": contact.get("city"),
        "organization": {
            "name": org.get("name"),
            "industry": org.get("industry"),
            "estimated_num_employees": org.get("estimated_num_employees"),
            "technologies": org.get("technologies"),
            "is_hiring": org.get("is_hiring"),
            "recent_funding": org.get("recent_funding"),
        },
    }


def on_compliance_shield_purchase(contact, sequences=None):
    """Route a $49/$197 Shield buyer to the next offer.

    Returns a queued pitch dict — status is always AWAITING_APPROVAL.
    Nothing is sent. If `sequences` is passed, the pitch is submitted
    to the approval gate, which returns PENDING_APPROVAL until a human
    approves it.
    """
    person = _person_from_contact(contact)
    score, breakdown, _ = score_prospect_multi(
        person, ICP_MODES["system_4_niche_agent"]
    )
    tier = "HOT" if score >= HOT_THRESHOLD else "WARM"
    first = person.get("first_name") or "there"
    org_name = person["organization"].get("name") or "your business"

    if tier == "HOT":
        offer = {
            "name": "DFY Compliance + Funnel",
            "price": "$3,500 one-time",
            "sequence_id": ASCENSION_SEQUENCES["high_ticket_3500"],
            "pitch": (
                f"Hey {first} — your compliance docs are done. Want me to build "
                "the rest too — sales page rewritten for FTC compliance plus "
                "the automations — done for you, $3,500 one time?"
            ),
        }
    else:
        offer = {
            "name": "Local Automation Retainer",
            "price": "$1,500 setup + $497/mo",
            "sequence_id": ASCENSION_SEQUENCES["retainer_497"],
            "pitch": (
                f"Hey {first} — your compliance docs are done. The next leak is "
                f"follow-up: missed calls, no reviews, leads going cold at "
                f"{org_name}. I can install missed-call text-back, review "
                "requests, and lead follow-up in 10 days — $1,500 setup + "
                "$497/mo. Want me to map it?"
            ),
        }

    sequence_result = None
    if sequences is not None:
        sequence_result = sequences.add_to_sequence(
            contact.get("id"), offer["sequence_id"]
        )

    return {
        "contact_id": contact.get("id"),
        "email": contact.get("email"),
        "score": score,
        "breakdown": breakdown,
        "tier": tier,
        "offer": offer,
        "status": "AWAITING_APPROVAL",
        "sequence_result": sequence_result,
    }
