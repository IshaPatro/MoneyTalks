"""Proves the real Role 1 engine is a drop-in replacement for
MockAnalyticsEngine: it satisfies the AnalyticsEngine protocol Role 2
codes against, and the full pipeline (upload -> compare -> rank ->
investigate -> explain -> memory -> narrative check) runs end to end on
the real 3-year Northstar AI dataset without any changes to
backend/agent_engine or backend/memory.
"""

from pathlib import Path

import pytest

from backend.finance_engine.engine import FinanceEngine
from backend.agent_engine.investigate import investigate_variance
from backend.agent_engine.narrative_check import verify_narrative_claim
from backend.memory.store import MemoryStore

REPO_ROOT = Path(__file__).resolve().parents[3]
SUMMARY_CSV = REPO_ROOT / "data" / "monthly_summary.csv"
TRANSACTIONS_CSV = REPO_ROOT / "data" / "transactions.csv"

pytestmark = pytest.mark.skipif(
    not SUMMARY_CSV.exists() or not TRANSACTIONS_CSV.exists(),
    reason="demo dataset not present",
)


@pytest.fixture()
def engine() -> FinanceEngine:
    return FinanceEngine.from_csv(SUMMARY_CSV, TRANSACTIONS_CSV)


def test_engine_satisfies_analytics_engine_protocol(engine: FinanceEngine):
    from backend.agent_engine.analytics_interface import AnalyticsEngine

    assert isinstance(engine, AnalyticsEngine)


def test_rank_variances_surfaces_subscription_revenue_first(engine: FinanceEngine):
    ranked = engine.rank_variances("2025-09", "2025-08", top_n=1)
    assert ranked[0].account == "Subscription Revenue"


def test_full_pipeline_produces_grounded_explanation(monkeypatch, engine: FinanceEngine):
    """Legal & Professional (the README's 'one-off expense' scenario) has
    a single dominant vendor, so this exercises the case where evidence
    should be non-empty. (Subscription Revenue's growth is broad-based
    across many customers in the real dataset -- see
    test_narrative_check_against_real_driver_data below -- so it's a
    genuinely different, and equally valid, shape of explanation.)"""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)  # deterministic template path

    variances = {v.account: v for v in engine.compare_periods("2025-09", "2025-08")}
    legal = variances["Legal & Professional"]

    explanation = investigate_variance(legal, engine, period="2025-09")

    # Every number the explanation cites must trace back to real driver data.
    assert f"{abs(legal.change_pct):.1f}" in explanation.headline
    assert explanation.driver_ids
    assert explanation.transaction_ids

    all_driver_ids = {d.driver_id for d in engine.breakdown_variance(legal.variance_id)}
    assert set(explanation.driver_ids).issubset(all_driver_ids)

    all_txn_ids = set(engine.dataset.transactions["transaction_id"])
    assert set(explanation.transaction_ids).issubset(all_txn_ids)


def test_multi_run_memory_survives_a_real_second_run(tmp_path, monkeypatch, engine: FinanceEngine):
    """Same multi-run scenario as the mocked demo, but driven by the real
    engine: confirm an explanation for one period, then verify the next
    period's investigation retrieves it."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    memory = MemoryStore(tmp_path / "memory.db")

    payroll_run1 = {v.account: v for v in engine.compare_periods("2025-08", "2025-07")}["Payroll"]
    investigate_variance(payroll_run1, engine, period="2025-08", memory=memory)
    memory.save_confirmed_context(
        account="Payroll", period="2025-08",
        explanation="Headcount growth in engineering drove the payroll increase.",
    )

    payroll_run2 = {v.account: v for v in engine.compare_periods("2025-09", "2025-08")}["Payroll"]
    explanation2 = investigate_variance(payroll_run2, engine, period="2025-09", memory=memory)

    assert explanation2.historical_context is not None
    assert "Headcount growth in engineering" in explanation2.historical_context


def test_narrative_check_supported_on_concentrated_legal_spend(engine: FinanceEngine, monkeypatch):
    """Legal & Professional's Sept 2025 spend is ~100% one vendor
    (Wilson Sonsini) -- a claim naming that vendor should be Supported."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    variances = {v.account: v for v in engine.compare_periods("2025-09", "2025-08")}
    legal = variances["Legal & Professional"]

    verdict = verify_narrative_claim(
        "Legal expense increased due to a one-time invoice from Wilson Sonsini.",
        legal, engine,
    )
    assert verdict.verdict == "supported"
    assert verdict.match_pct == pytest.approx(1.0, abs=0.01)


def test_narrative_check_flags_overstated_single_customer_claim(engine: FinanceEngine, monkeypatch):
    """Subscription Revenue's real growth is broad-based across many
    customers (the top single customer is only ~9% of the increase).
    A claim crediting one customer for the whole quarter's growth should
    NOT be rubber-stamped -- this is exactly the kind of overstated
    narrative the feature exists to catch."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    variances = {v.account: v for v in engine.compare_periods("2025-09", "2025-08")}
    sub_rev = variances["Subscription Revenue"]
    drivers = engine.breakdown_variance(sub_rev.variance_id, dimension="customer")
    top_entity = max((d for d in drivers if d.entity != "Other"), key=lambda d: abs(d.change)).entity

    verdict = verify_narrative_claim(
        f"Subscription revenue grew this quarter thanks to strong demand from {top_entity}.",
        sub_rev, engine,
    )
    assert verdict.verdict == "unsupported"
    assert top_entity in verdict.claimed_entities
    assert verdict.match_pct < 0.15


def test_narrative_check_catches_wrong_direction_on_real_data(engine: FinanceEngine, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    variances = {v.account: v for v in engine.compare_periods("2025-09", "2025-08")}
    sub_rev = variances["Subscription Revenue"]  # actually grew 27.7%

    verdict = verify_narrative_claim(
        "Subscription revenue declined this quarter.", sub_rev, engine,
    )
    assert verdict.verdict == "contradicted"
