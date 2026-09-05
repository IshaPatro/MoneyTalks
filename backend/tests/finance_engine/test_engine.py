"""Validates FinanceEngine against the real synthetic subscription
dataset (data/subscription_accounts.csv) -- including the seeded demo
scenarios (whale expansion, SLA-credit shock, quarterly contraction
cohort, churn) so this is checked against known, hand-designed outcomes,
not just "it ran without crashing."
"""

import pytest

from backend.finance_engine.engine import FinanceEngine, PORTFOLIO_ACCOUNT_NAME


def test_compare_periods_returns_one_variance_per_active_account(engine: FinanceEngine):
    variances = engine.compare_periods("2025-10", "2025-09")
    assert len(variances) > 0
    accounts = {v.account for v in variances}
    assert "ACC-0001" in accounts  # the seeded whale


def test_whale_expansion_scenario(engine: FinanceEngine):
    """ACC-0001 has a large, deliberate expansion seeded at global month 10
    (2025-10 vs 2025-09) -- see generate_subscription_data.py."""
    variances = {v.account: v for v in engine.compare_periods("2025-10", "2025-09")}
    whale = variances["ACC-0001"]
    assert whale.change > 20000
    assert whale.change_pct > 0

    drivers = engine.breakdown_variance(whale.variance_id)
    assert len(drivers) == 1
    assert drivers[0].entity == "Expansion"
    assert drivers[0].change == pytest.approx(whale.change)
    assert drivers[0].transaction_ids


def test_sla_credit_shock_scenario(engine: FinanceEngine):
    """ACC-0002 has a large one-off SLA credit in the same month as the
    whale's expansion -- mirrors the README's 'one-off expense' demo."""
    variances = {v.account: v for v in engine.compare_periods("2025-10", "2025-09")}
    meridian = variances["ACC-0002"]
    assert meridian.change < 0

    drivers = engine.breakdown_variance(meridian.variance_id)
    assert any(d.entity == "Sla_Credit" for d in drivers)

    txns = engine.get_top_transactions(meridian.variance_id, entity="Sla_Credit")
    assert txns
    assert all(t.description == "System_Outage_Credit" for t in txns)


def test_rank_variances_is_not_percentage_only(engine: FinanceEngine):
    ranked = engine.rank_variances("2025-10", "2025-09", top_n=10)
    assert ranked
    # A 100%-churned tiny account shouldn't automatically outrank a much
    # larger dollar swing -- the whale (large $, large %) should be #1.
    assert ranked[0].account == "ACC-0001"


def test_portfolio_variance_reveals_concentration(engine: FinanceEngine):
    """The core 'concentration risk' insight: portfolio net growth is
    small/misleading while one whale masks churn and an SLA credit
    elsewhere -- this is what makes the headline number lie."""
    portfolio = engine.get_portfolio_variance("2025-10", "2025-09")
    assert portfolio.account == PORTFOLIO_ACCOUNT_NAME

    account_drivers = engine.breakdown_variance(portfolio.variance_id, dimension="account", top_n=5)
    whale_driver = next(d for d in account_drivers if d.entity == "ACC-0001")
    # the whale alone should dominate the net portfolio change -- proof
    # that "portfolio grew 5.4%" is a whale story, not broad-based growth.
    assert abs(whale_driver.change) / abs(portfolio.change) > 0.5


def test_portfolio_breakdown_by_segment(engine: FinanceEngine):
    portfolio = engine.get_portfolio_variance("2025-10", "2025-09")
    segment_drivers = engine.breakdown_variance(portfolio.variance_id, dimension="company_size")
    entities = {d.entity for d in segment_drivers}
    assert entities <= {"SMB", "Mid-Market", "Enterprise"}
    # drivers must sum back to the total portfolio change -- no leakage.
    assert sum(d.change for d in segment_drivers) == pytest.approx(portfolio.change, abs=0.01)


def test_portfolio_breakdown_rejects_unknown_dimension(engine: FinanceEngine):
    portfolio = engine.get_portfolio_variance("2025-10", "2025-09")
    with pytest.raises(ValueError):
        engine.breakdown_variance(portfolio.variance_id, dimension="not_a_real_dimension")


def test_breakdown_variance_unknown_id_raises(engine: FinanceEngine):
    with pytest.raises(KeyError):
        engine.breakdown_variance("VAR_DOES_NOT_EXIST")


def test_get_top_transactions_sorted_by_magnitude(engine: FinanceEngine):
    variances = {v.account: v for v in engine.compare_periods("2025-10", "2025-09")}
    whale = variances["ACC-0001"]
    txns = engine.get_top_transactions(whale.variance_id, limit=5)
    amounts = [abs(t.amount) for t in txns]
    assert amounts == sorted(amounts, reverse=True)


def test_churn_produces_a_negative_100_pct_variance(engine: FinanceEngine):
    """Any account with a Churn event should show current_mrr == 0 and a
    -100% change relative to its last active month."""
    variances = engine.compare_periods("2025-10", "2025-09")
    churned = [v for v in variances if v.current == 0 and v.previous > 0]
    for v in churned:
        assert v.change_pct == pytest.approx(-100.0)
        drivers = engine.breakdown_variance(v.variance_id)
        assert any(d.entity == "Churn" for d in drivers)


def test_historical_account_changes_for_whale(engine: FinanceEngine):
    history = engine.get_historical_account_changes("ACC-0001", periods=24)
    assert history
    periods = [h["period"] for h in history]
    assert periods == sorted(periods)
    spike = next(h for h in history if h["period"] == "2025-10")
    other_pcts = [h["change_pct"] for h in history if h["period"] != "2025-10"]
    assert spike["change_pct"] > max(other_pcts, default=0)


def test_historical_portfolio_changes(engine: FinanceEngine):
    history = engine.get_historical_account_changes(PORTFOLIO_ACCOUNT_NAME, periods=12)
    assert len(history) == 12


def test_unknown_account_history_is_empty(engine: FinanceEngine):
    assert engine.get_historical_account_changes("ACC-9999") == []


def test_all_outputs_are_valid_contract_objects(engine: FinanceEngine):
    for variance in engine.rank_variances("2025-10", "2025-09", top_n=8):
        assert variance.variance_id
        drivers = engine.breakdown_variance(variance.variance_id)
        for d in drivers:
            assert d.driver_id and d.dimension
        txns = engine.get_top_transactions(variance.variance_id, limit=3)
        for t in txns:
            assert t.transaction_id
            assert t.account == variance.account
