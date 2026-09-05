"""Assembles ready-to-render VarianceCards for the Overview/Investigation
screens (README section 15) from Role 1's engine + Role 2's investigation.

This is the one function the frontend (or a future FastAPI route, Role 3's
`backend/app/`) should call per period comparison -- it returns fully-formed
cards, so no implicit assembly happens client-side. Lives outside
agent_engine/finance_engine because it depends on both.
"""

from __future__ import annotations

from typing import Optional

from backend.contracts.frontend_view import VarianceCard, build_variance_card
from backend.contracts.schemas import ConfirmedContextRef
from backend.agent_engine.explain import generate_explanation
from backend.agent_engine.drivers import select_important_drivers
from backend.finance_engine.engine import FinanceEngine
from backend.memory.store import MemoryStore


def build_dashboard(
    engine: FinanceEngine,
    current_period: str,
    comparison_period: str,
    memory: Optional[MemoryStore] = None,
    top_n: int = 5,
) -> list[VarianceCard]:
    """`engine` needs rank_variances() in addition to the AnalyticsEngine
    protocol (breakdown_variance/get_top_transactions/get_historical_account_changes),
    so this takes a concrete FinanceEngine rather than the narrower protocol."""
    variances = engine.rank_variances(current_period, comparison_period, top_n=top_n)

    cards: list[VarianceCard] = []
    for rank, variance in enumerate(variances, start=1):
        drivers = engine.breakdown_variance(variance.variance_id)
        named_drivers, named_share = select_important_drivers(variance, drivers)

        # "Other" (the residual bucket) has no literal transactions -- if
        # it's the headline driver, still surface evidence from the
        # largest *named* real entities so the card is never evidence-free
        # just because growth happens to be broad-based.
        evidence_drivers = [d for d in named_drivers if d.entity != "Other"]
        if not evidence_drivers:
            evidence_drivers = sorted(
                (d for d in drivers if d.entity != "Other"),
                key=lambda d: abs(d.change), reverse=True,
            )[:3]

        transaction_ids: list[str] = []
        top_transactions = []
        for d in evidence_drivers:
            txns = engine.get_top_transactions(variance.variance_id, entity=d.entity)
            transaction_ids.extend(t.transaction_id for t in txns)
            top_transactions.extend(txns)

        history = engine.get_historical_account_changes(variance.account)

        confirmed_context = None
        if memory is not None:
            prior = memory.get_previous_context(variance.account, current_period)
            if prior:
                confirmed_context = ConfirmedContextRef(
                    account=prior[0].account, period=prior[0].period,
                    explanation=prior[0].explanation, entity=prior[0].entity,
                )

        note = None
        if confirmed_context:
            note = f'A similar movement was previously confirmed as: "{confirmed_context.explanation}" ({confirmed_context.period}).'

        explanation = generate_explanation(
            variance=variance, named_drivers=named_drivers, named_share=named_share,
            transaction_ids=transaction_ids, historical_note=note,
        )

        cards.append(
            build_variance_card(
                variance=variance, rank=rank, drivers=drivers,
                top_transactions=top_transactions[:10], explanation=explanation,
                history=history, confirmed_context=confirmed_context,
                is_material=True,
            )
        )
    return cards
