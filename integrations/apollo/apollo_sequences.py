"""Apollo sequences. Nothing sends without an approval pass.

FIXED vs the pasted draft: it used os.getenv without importing os.
"""
import os

from .apollo_client import ApolloClient


class ApolloSequences:
    def __init__(self):
        self.client = ApolloClient()

    def add_to_sequence(self, contact_id, sequence_id, approval_passed=False):
        if os.getenv("APOLLO_APPROVAL_REQUIRED", "true") == "true" and not approval_passed:
            return {"status": "PENDING_APPROVAL", "contact_id": contact_id}

        return self.client.post(
            "email_accounts/add_contact_to_sequence",
            {
                "contact_ids": [contact_id],
                "sequence_id": sequence_id,
                "sequence_no_email": False,
            },
        )
