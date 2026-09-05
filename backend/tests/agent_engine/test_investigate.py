import os

from backend.agent_engine.analytics_interface import MOCK_VARIANCES, MockAnalyticsEngine
from backend.agent_engine.investigate import investigate_variance
from backend.memory.store import MemoryStore


def test_investigate_variance_enterprise_revenue_no_llm(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    analytics = MockAnalyticsEngine()
    variance = MOCK_VARIANCES["VAR_001"]

    explanation = investigate_variance(variance, analytics)

    assert explanation.variance_id == "VAR_001"
    assert "31.7%" in explanation.headline
    assert explanation.driver_ids  # evidence present
    assert explanation.transaction_ids
    # LLM must not have invented a different percentage than Role 1 gave us.
    assert "31.7" in explanation.explanation


def test_investigate_variance_includes_previous_confirmed_context(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    db_path = tmp_path / "memory.db"
    memory = MemoryStore(db_path)
    memory.save_confirmed_context(
        account="Sales Commissions",
        period="2026-06",
        explanation="Quarter-end commission payments.",
    )

    analytics = MockAnalyticsEngine()
    variance = MOCK_VARIANCES["VAR_003"]  # Sales Commissions

    explanation = investigate_variance(variance, analytics, period="2026-09", memory=memory)

    assert explanation.historical_context is not None
    assert "Quarter-end commission payments" in explanation.historical_context


def test_investigate_variance_evidence_ids_trace_to_real_drivers():
    analytics = MockAnalyticsEngine()
    variance = MOCK_VARIANCES["VAR_002"]  # Legal one-off expense

    explanation = investigate_variance(variance, analytics)

    all_driver_ids = {d.driver_id for d in analytics.breakdown_variance(variance.variance_id)}
    assert set(explanation.driver_ids).issubset(all_driver_ids)
