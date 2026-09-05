"""Standalone demo for the optional narrative fact-check feature.

Run directly:

    python3 -m backend.agent_engine.demo_narrative

Prints a synthetic "Northstar AI investor call" quote next to what the
underlying transaction data actually shows, for each of the three seeded
demo scenarios (enterprise growth, legal one-off, recurring commissions).
This is deliberately explicit/side-by-side rather than a single paragraph,
so the verification logic is visible in the demo, not just asserted.
"""

from __future__ import annotations

from backend.agent_engine.analytics_interface import MOCK_VARIANCES, MockAnalyticsEngine
from backend.agent_engine.narrative_check import verify_narrative_claim
from backend.contracts.schemas import NarrativeVerdict, Variance

# Scripted "investor call" lines for the Northstar AI demo dataset.
# Deliberately includes one fully-supported, one partial, and one
# contradicted line to show the feature working both ways.
TRANSCRIPT = [
    ("VAR_001", "Enterprise revenue growth this quarter was driven by strong "
                "expansion with Acme, Globex, and Umbrella."),
    ("VAR_002", "Legal costs were flat quarter over quarter."),
    ("VAR_003", "Sales commission expense declined this quarter as the sales "
                "team missed targets."),
]

_VERDICT_ICON = {
    "supported": "✅",
    "partially_supported": "⚠️",
    "unsupported": "❌",
    "contradicted": "\U0001f6a8",
    "unverifiable": "❓",
}


def _print_card(variance: Variance, verdict: NarrativeVerdict) -> None:
    icon = _VERDICT_ICON.get(verdict.verdict, "?")
    print("=" * 72)
    print(f'"{verdict.claim_text}"')
    print("-" * 72)
    print(f"Account:        {variance.account}")
    print(f"Actual change:  {variance.change:+,.0f} ({variance.change_pct:+.1f}%)")
    print(f"Claim mentions: {verdict.claimed_entities or '(no known entity named)'}")
    print(f"Real top drivers: {verdict.actual_top_entities}")
    if verdict.match_pct is not None:
        print(f"Named entities cover: {verdict.match_pct * 100:.0f}% of the actual change")
    print(f"VERDICT: {icon} {verdict.verdict.upper().replace('_', ' ')}")
    print(f"Why: {verdict.reasoning}")
    print(f"Evidence: driver_ids={verdict.driver_ids} transaction_ids={verdict.transaction_ids}")
    print()


def main() -> None:
    analytics = MockAnalyticsEngine()
    for variance_id, claim in TRANSCRIPT:
        variance = MOCK_VARIANCES[variance_id]
        verdict = verify_narrative_claim(claim, variance, analytics)
        _print_card(variance, verdict)


if __name__ == "__main__":
    main()
