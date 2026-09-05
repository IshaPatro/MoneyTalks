"""Orchestrates the investigation of a single variance (README section 11).

    1. Receive variance
    2. Request driver breakdown
    3. Identify largest contributors
    4. Request supporting transactions
    5. Check historical context (Role 1's period-over-period history)
    6. Check previous memory (Role 2's confirmed-context store)
    7. Prepare explanation
    8. Return driver_ids / transaction_ids as evidence
"""

from __future__ import annotations

from typing import Optional

from backend.contracts.schemas import Explanation, Variance
from backend.memory.store import MemoryStore, get_previous_context
from backend.agent_engine.analytics_interface import AnalyticsEngine
from backend.agent_engine.drivers import select_important_drivers
from backend.agent_engine.explain import generate_explanation


def _historical_note(
    variance: Variance,
    analytics: AnalyticsEngine,
    period: Optional[str],
    memory: Optional[MemoryStore],
) -> Optional[str]:
    """Combine Role 1's raw history with Role 2's confirmed-context memory
    into a single sentence, without letting memory override current data."""
    notes = []

    history = analytics.get_historical_account_changes(variance.account)
    if history:
        notes.append(
            f"{variance.account} has moved similarly in {len(history)} "
            f"prior period(s)."
        )

    if period is not None:
        prior = (
            memory.get_previous_context(variance.account, period)
            if memory
            else get_previous_context(variance.account, period)
        )
        if prior:
            most_recent = prior[0]
            notes.append(
                f"A similar movement was previously confirmed as: "
                f'"{most_recent.explanation}" ({most_recent.period}).'
            )

    return " ".join(notes) if notes else None


def investigate_variance(
    variance: Variance,
    analytics: AnalyticsEngine,
    period: Optional[str] = None,
    memory: Optional[MemoryStore] = None,
) -> Explanation:
    """Run the full investigation workflow for one variance and return a
    structured Explanation with evidence (driver_ids, transaction_ids)."""

    drivers = analytics.breakdown_variance(variance.variance_id)
    named_drivers, named_share = select_important_drivers(variance, drivers)

    transaction_ids: list[str] = []
    for d in named_drivers:
        txns = analytics.get_top_transactions(variance.variance_id, entity=d.entity)
        transaction_ids.extend(t.transaction_id for t in txns)

    note = _historical_note(variance, analytics, period, memory)

    return generate_explanation(
        variance=variance,
        named_drivers=named_drivers,
        named_share=named_share,
        transaction_ids=transaction_ids,
        historical_note=note,
    )
