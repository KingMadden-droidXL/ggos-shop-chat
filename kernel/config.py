"""5 ICP definitions — one hunting mode per Cashflow System.

PRICE NOTE: offer strings come from the AI Cashflow Systems 2026 doc
as REPORTED ranges from other sellers, not guarantees (the doc says
so twice). System 4's price is settled by the doc + latest paste:
$49 basic / $197 pro (doc range $47-$197 one-time / $19-$49/mo).

SEQUENCE IDS ARE PLACEHOLDERS. No Apollo sequences exist yet; replace
each SEQ_* value with the real sequence ID from Apollo before any
sequence step runs.
"""
ICP_MODES = {
    "system_1_local_automation": {
        "name": "AI Automation for Local Biz",
        "offer": "$1,500-$3,500 setup + $297-$697/mo",
        "titles": ["Owner", "CEO", "Founder", "Office Manager"],
        "industries": ["Dentist", "Real Estate", "Salon", "Gym", "Contractor", "Restaurant"],
        "territory": ["New Mexico, US", "Texas, US"],
        "company_size": ["1,10", "11,50"],
        "keywords": ["missed calls", "no reviews", "manual booking"],
        "apollo_sequence_id": "SEQ_LOCAL_AUTO_01",
    },
    "system_2_faceless": {
        "name": "Faceless Content + Digital Products",
        "offer": "$27-$97",
        "titles": ["Creator", "Influencer", "Coach", "Founder"],
        "industries": ["Content Creation", "Coaching", "Education"],
        "keywords": ["TikTok", "Reels", "YouTube Shorts"],
        "apollo_sequence_id": "SEQ_FACELESS_01",
    },
    "system_3_high_ticket": {
        "name": "High-Ticket Freelance Services",
        "offer": "$1,500-$4,000 per project",
        "titles": ["CEO", "Founder", "CMO", "Marketing Director"],
        "industries": ["SaaS", "Software", "Marketing Agency"],
        "keywords": ["funding", "hiring copywriter", "new offer"],
        "apollo_sequence_id": "SEQ_HIGHTICKET_01",
    },
    "system_4_niche_agent": {  # PRIMARY
        "name": "Niche AI Agent - Compliance Shield",
        "offer": "$49 basic / $197 pro",
        "titles": ["Owner", "CEO", "COO", "CTO", "Compliance Officer", "IT Director"],
        "industries": ["Artificial Intelligence", "SaaS", "Software", "Legal Services"],
        "territory": ["New Mexico, US", "Texas, US", "United States"],
        "company_size": ["1,10", "11,50", "51,200"],
        "keywords": ["AI compliance", "EU AI Act", "FTC", "GDPR", "AI policy"],
        "apollo_sequence_id": "SEQ_COMPLIANCE_SHIELD_01",
    },
    "system_5_local_service": {
        "name": "Local Service Supercharged",
        "offer": "Service biz + AI admin",
        "titles": ["Owner", "Founder"],
        "industries": ["Pressure Washing", "Detailing", "Junk Removal", "Lawn Care", "Window Cleaning"],
        "territory": ["New Mexico, US", "Texas, US"],
        "company_size": ["1,10", "11,50"],
        "apollo_sequence_id": "SEQ_LOCAL_SVC_01",
    },
}

# Ascension upsell sequences (ascension.OS). Placeholders — replace
# with real Apollo sequence IDs before any sequence step runs.
ASCENSION_SEQUENCES = {
    "high_ticket_3500": "SEQ_HIGH_TICKET_3500",  # HOT buyer -> $3,500 DFY
    "retainer_497": "SEQ_RETAINER_497",  # WARM buyer -> $497/mo retainer
}
