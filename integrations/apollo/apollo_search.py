"""Net-new prospecting via Apollo people/company search.

Endpoint names follow Apollo API v1 as used in the build spec; they have
NOT been verified against a live Apollo account yet (no key on file).
"""
from .apollo_client import ApolloClient


class ApolloSearch:
    def __init__(self):
        self.client = ApolloClient()

    def people_search(self, icp: dict, page=1, per_page=25):
        # ICP from Intelligence.OS
        payload = {
            "page": page,
            "per_page": per_page,
            "person_titles": icp.get(
                "titles", ["Owner", "CEO", "COO", "CTO", "Compliance Officer"]
            ),
            "organization_locations": icp.get(
                "territory", ["New Mexico, US", "Texas, US"]
            ),
            "organization_num_employees_ranges": icp.get(
                "company_size", ["1,10", "11,50", "51,200"]
            ),
            "q_organization_keyword_tags": icp.get(
                "industries", ["AI", "SaaS", "Software"]
            ),
            "person_seniorities": ["c_suite", "owner", "director", "vp"],
        }
        return self.client.post("mixed_people/search", payload)

    def company_search(self, domain=None, name=None):
        if domain:
            return self.client.get("organizations/enrich", params={"domain": domain})
        return self.client.post(
            "mixed_companies/search", {"q_organization_name": name}
        )
