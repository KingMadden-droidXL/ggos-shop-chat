"""Prospect scoring for the 5-mode hunter. Max 100; HOT needs 80.

Signals, all read from the prospect record Apollo returns — nothing
invented about the prospect:
- decision maker: 25 (owner/ceo/coo/founder) or 15 (director/vp/manager/compliance)
- industry match: 20
- company size 1-200: 15
- tech/compliance signal: 15 (organization.technologies present)
- local fit: 5 (Clovis / Albuquerque / Lubbock / Amarillo / Austin / Dallas)
- recent growth: 10 — only when the record carries an explicit flag
  (is_hiring / recent_funding); 0 otherwise
- buying signal: 10 — only when the record carries an explicit
  _buying_signal flag; 0 otherwise

FIXED vs the pasted draft: the draft's five signals maxed at 80 while
HOT needed 80, so only a perfect score ever counted as HOT. Restoring
the growth + buying signals (from the earlier paste) makes HOT
reachable: all five base signals = 80 exactly.
"""


def score_prospect_multi(person, icp):
    score = 0
    breakdown = {}
    title = (person.get("title") or "").lower()

    if any(t in title for t in ("owner", "ceo", "coo", "founder")):
        score += 25
        breakdown["decision_maker"] = 25
    elif any(t in title for t in ("director", "vp", "manager", "compliance")):
        score += 15
        breakdown["decision_maker"] = 15

    org = person.get("organization") or {}
    org_ind = org.get("industry") or ""
    if any(ind.lower() in org_ind.lower() for ind in icp.get("industries", [])):
        score += 20
        breakdown["industry"] = 20

    size = org.get("estimated_num_employees", 0) or 0
    if 1 <= size <= 200:
        score += 15
        breakdown["size"] = 15

    if org.get("technologies"):
        score += 15
        breakdown["tech"] = 15

    city = (person.get("city") or "").lower()
    if city in ("clovis", "albuquerque", "lubbock", "amarillo", "austin", "dallas"):
        score += 5
        breakdown["local"] = 5

    if org.get("is_hiring") or org.get("recent_funding"):
        score += 10
        breakdown["growth"] = 10

    if person.get("_buying_signal"):
        score += 10
        breakdown["buying_signal"] = 10

    return score, breakdown, icp["name"]
