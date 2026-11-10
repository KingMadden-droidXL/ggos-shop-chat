"""boot — daily loop for the 5 income streams.

Run:  APOLLO_API_KEY=... python boot.py   (or via .env)
       python boot.py --mode system_4_niche_agent   # Week 1: Mode 4 only
       python boot.py --per-mode 25

20 prospects per mode = 100/day max. Enrichment only for score >= 60,
behind the shared governor (default 100/day).

Prints the approval queue. Nothing is sent, sequenced, or charged
from here — HOT prospects wait for a human APPROVE / REJECT / EDIT.
"""
import argparse

from kernel.config import ICP_MODES
from services.prospecting import ProspectingOS


def select_modes(requested):
    """Pure helper: None/empty -> all modes; else the named ones."""
    if not requested:
        return list(ICP_MODES)
    unknown = [m for m in requested if m not in ICP_MODES]
    if unknown:
        raise ValueError(f"unknown mode(s): {', '.join(unknown)}")
    return list(requested)


def main(per_mode=20, modes=None):
    prospecting = ProspectingOS()
    results = prospecting.run_modes(select_modes(modes), per_mode=per_mode)

    for system, prospects in results.items():
        hot = [p for p in prospects if p["tier"] == "HOT"]
        print(
            f"{system}: {len(hot)} HOT / {len(prospects)} total "
            f"- credits used: {prospecting.governor.used}"
        )

    # Human approval gate - you see this in Slack/Dashboard:
    # [SYSTEM 4 HOT] John Smith, CEO @ AI Startup, Score 85 -> "Hey John - ..."
    # APPROVE / REJECT / EDIT -> then -> Apollo sequence
    for system, prospects in results.items():
        for p in prospects:
            if p["tier"] == "HOT":
                name = p["prospect"].get("name") or p["prospect"].get("email")
                print(
                    f"APPROVAL NEEDED [{system}]: {name} "
                    f"score {p['score']} -> sequence {p['sequence_id']}?"
                )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        action="append",
        default=None,
        help="Run only this mode (repeatable). Default: all 5 modes.",
    )
    parser.add_argument("--per-mode", type=int, default=20)
    args = parser.parse_args()
    main(per_mode=args.per_mode, modes=args.mode)
