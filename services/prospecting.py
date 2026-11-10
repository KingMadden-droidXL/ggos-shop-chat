"""ProspectingOS: 5-mode parallel hunter over one shared Credit Governor.

Flow per prospect (the doc's discipline): free Apollo search -> score
-> reject < 40 -> enrich only >= 60 (costs a credit, governor enforced
once, inside the enrichment step) -> create/update contact -> draft
peer-style outreach -> AWAITING_APPROVAL. Nothing is sent without a
human approval.

FIXED vs the pasted draft:
- The governor is created once and shared with enrichment; no double
  counting (the draft consumed a credit in two places per enrich).
- If the governor skips an enrichment, the raw prospect (not the
  {"skipped": ...} dict) is used for the contact.
- All 5 systems have their own outreach template. The draft only had
  3, so systems 2 and 5 would have been sent the Compliance Shield
  message.
- Templates carry no invented claims about the prospect (no "losing
  30%", no "most shops in Clovis do"). Each is a question + a free
  mini-audit/sample offer, peer tone, under 80 words.
"""
from integrations.apollo.apollo_contacts import ApolloContacts
from integrations.apollo.apollo_enrichment import ApolloEnrichment, CreditGovernor
from integrations.apollo.apollo_search import ApolloSearch
from kernel.config import ICP_MODES
from services.intelligence import score_prospect_multi


class ProspectingOS:
    def __init__(self, governor=None):
        self.search = ApolloSearch()
        self.governor = governor or CreditGovernor()
        self.enrichment = ApolloEnrichment(governor=self.governor)
        self.contacts = ApolloContacts()

    def run_modes(self, mode_keys, per_mode=25):
        all_qualified = {}
        for mode_key in mode_keys:
            icp = ICP_MODES[mode_key]
            raw = self.search.people_search(icp, per_page=per_mode)
            qualified = []

            for person in raw.get("people", []):
                # Multi-system scoring
                score, breakdown, best_fit_system = score_prospect_multi(person, icp)

                if score < 40:
                    continue  # REJECT

                tier = "HOT" if score >= 80 else "WARM" if score >= 60 else "NURTURE"

                # CREDIT GOVERNOR - only enrich HOT/WARM
                enrich_data = person
                if score >= 60:
                    enriched = self.enrichment.enrich_person(person, score)
                    if not enriched.get("skipped"):
                        enrich_data = enriched

                contact = self.contacts.create_or_update(
                    {**enrich_data, "_gangster_score": score}
                )

                qualified.append(
                    {
                        "system": mode_key,
                        "offer": icp["offer"],
                        "sequence_id": icp["apollo_sequence_id"],
                        "prospect": person,
                        "score": score,
                        "tier": tier,
                        "breakdown": breakdown,
                        "best_fit": best_fit_system,
                        "contact_id": (contact.get("contact") or {}).get("id"),
                        "status": "AWAITING_APPROVAL",
                        "outreach_draft": self.generate_peer_outreach(
                            person, icp, mode_key
                        ),
                    }
                )

            all_qualified[mode_key] = qualified

        return all_qualified

    def run_all_modes(self, per_mode=25):
        return self.run_modes(list(ICP_MODES), per_mode=per_mode)

    def generate_peer_outreach(self, person, icp, system):
        # From the doc's winning prompt: under 80 words, specific problem,
        # free mini-audit/sample, peer tone — not a salesperson.
        first = person.get("first_name") or "there"
        org = (person.get("organization") or {}).get("name") or "your business"
        templates = {
            "system_1_local_automation": (
                f"Hey {first} — quick question about {org}: are missed calls "
                "and follow-ups eating time after hours? I set up missed-call "
                "text-back and review flows for local shops in about 10 days. "
                "Want a free mini-audit of your current follow-up?"
            ),
            "system_2_faceless": (
                f"Hey {first} — your content is already doing the work. The "
                "fastest next dollar is usually turning it into a small digital "
                "product, a prompt pack or a system. I build those from what's "
                "already performing. Want a free sample outline from one of "
                "your best posts?"
            ),
            "system_3_high_ticket": (
                f"Hey {first} — {org}'s offer is solid. I fix sales pages for "
                "AI and SaaS offers so the compliance wording doesn't cost "
                "conversions. Want 3 quick headline rewrites as a sample?"
            ),
            "system_4_niche_agent": (
                f"Hey {first} — saw you're building with AI. EU AI Act and FTC "
                "rules now ask for disclosures and risk docs. I built a "
                "Compliance Shield pack that generates them in about 5 minutes. "
                "Want the free checklist version to check your exposure?"
            ),
            "system_5_local_service": (
                f"Hey {first} — running {org} means quotes, reviews, and "
                "follow-ups on top of the actual work. I set up AI quotes and "
                "review follow-ups for local service crews. Want a free "
                "mini-audit of your current follow-up?"
            ),
        }
        return templates.get(system, templates["system_4_niche_agent"])
