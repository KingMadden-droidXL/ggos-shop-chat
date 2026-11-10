"""Apollo contacts: your owned list."""
from .apollo_client import ApolloClient


class ApolloContacts:
    def __init__(self):
        self.client = ApolloClient()

    def create_or_update(self, enriched_data):
        # Apollo contacts are your owned list
        return self.client.post(
            "contacts",
            {
                "first_name": enriched_data.get("first_name"),
                "last_name": enriched_data.get("last_name"),
                "email": enriched_data.get("email"),
                "organization_name": (enriched_data.get("organization") or {}).get("name"),
                "title": enriched_data.get("title"),
                "custom_fields": {
                    "gangster_score": enriched_data.get("_gangster_score")
                },
            },
        )
