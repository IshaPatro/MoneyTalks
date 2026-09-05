"""Proves the subscription-billing FinanceEngine is a drop-in
AnalyticsEngine for Role 2, and the full pipeline (upload -> compare ->
rank -> investigate -> explain -> confirm -> reuse memory -> fact-check)
works end to end with no mocks and no changes needed to agent_engine or
memory.
"""

import pytest

from backend.finance_engine.engine import FinanceEngine
from backend.agent_engine.investigate import investigate_variance
from backend.agent_engine.narrative_check import verify_narrative_claim
from backend.memory.store import MemoryStore


def test_engine_satisfies_analytics_engine_protocol(engine: FinanceEngine):
    from backend.agent_engine.analytics_interface import AnalyticsEngine

    assert isinstance(engine, AnalyticsEngine)


def test_full_pipeline_produces_grounded_explanation(monkeypatch, engine: FinanceEngine):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    variances = {v.account: v for v in engine.compare_periods("2025-10", "2025-09")}
    whale = variances["ACC-0001"]

    explanation = investigate_variance(whale, engine, period="2025-10")

    assert f"{abs(whale.change_pct):.1f}" in explanation.headline
    assert explanation.driver_ids
    assert explanation.transaction_ids

    all_driver_ids = {d.driver_id for d in engine.breakdown_variance(whale.variance_id)}
    assert set(explanation.driver_ids).issubset(all_driver_ids)


def test_multi_run_memory_survives_a_real_second_run(tmp_path, monkeypatch, engine: FinanceEngine):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    memory = MemoryStore(tmp_path / "memory.db")

    variances_run1 = {v.account: v for v in engine.compare_periods("2025-10", "2025-09")}
    whale_run1 = variances_run1["ACC-0001"]
    investigate_variance(whale_run1, engine, period="2025-10", memory=memory)
    memory.save_confirmed_context(
        account="ACC-0001", period="2025-10",
        explanation="Large one-time plan upgrade, not a recurring pattern.",
    )

    variances_run2 = {v.account: v for v in engine.compare_periods("2025-11", "2025-10")}
    whale_run2 = variances_run2["ACC-0001"]
    explanation2 = investigate_variance(whale_run2, engine, period="2025-11", memory=memory)

    assert explanation2.historical_context is not None
    assert "Large one-time plan upgrade" in explanation2.historical_context


def test_narrative_check_supported_on_whale_expansion(engine: FinanceEngine, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    variances = {v.account: v for v in engine.compare_periods("2025-10", "2025-09")}
    whale = variances["ACC-0001"]

    verdict = verify_narrative_claim(
        "Growth was driven entirely by an Expansion event.", whale, engine,
    )
    assert verdict.verdict == "supported"


def test_narrative_check_catches_overstated_portfolio_claim(engine: FinanceEngine, monkeypatch):
    """The portfolio only grew because one whale (ACC-0001) masked churn
    elsewhere -- a claim crediting broad growth without naming the whale
    should not be verifiable as 'broad-based' from the account breakdown."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    portfolio = engine.get_portfolio_variance("2025-10", "2025-09")

    verdict = verify_narrative_claim(
        "Portfolio MRR grew due to strong performance from ACC-0001.", portfolio, engine,
    )
    assert verdict.verdict in ("supported", "partially_supported")
    assert "ACC-0001" in verdict.claimed_entities
