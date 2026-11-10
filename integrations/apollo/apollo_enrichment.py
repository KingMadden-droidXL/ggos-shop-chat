"""Enrichment behind the Credit Governor.

FIXED vs the pasted draft:
- One shared governor. The caller owns it and passes it in, so the
  daily limit is enforced in exactly one place. (The draft created a
  second governor inside ApolloEnrichment and counted each enrichment
  twice, so the limit never actually held.)
- consume() happens exactly once, here, after a successful enrich.

NOTE: `used` lives in memory — it resets when the process restarts.
A daily batch run starts at 0, which matches a once-a-day limit;
running twice a day could double-spend. Persist it (DB/Redis) before
running on a schedule.
"""
import os

from .apollo_client import ApolloClient


class CreditGovernor:
    def __init__(self, limit=None):
        self.limit = int(
            limit if limit is not None else os.getenv("APOLLO_DAILY_CREDIT_LIMIT", 100)
        )
        self.used = 0  # In prod, store in Redis / Firestore

    def can_enrich(self, score: int) -> bool:
        threshold = int(os.getenv("APOLLO_ENRICH_SCORE_THRESHOLD", 60))
        if score < threshold:
            return False
        if self.used >= self.limit:
            return False
        return True

    def consume(self, n=1):
        self.used += n


class ApolloEnrichment:
    def __init__(self, governor=None):
        self.client = ApolloClient()
        self.governor = governor or CreditGovernor()

    def enrich_person(self, prospect, score):
        if not self.governor.can_enrich(score):
            return {
                "skipped": True,
                "reason": f"score {score} below threshold or daily limit reached",
            }

        # Apollo people/match - enrich by email or id
        payload = (
            {"id": prospect.get("id")}
            if prospect.get("id")
            else {"email": prospect.get("email")}
        )
        result = self.client.post("people/match", payload)
        self.governor.consume(1)
        return result
