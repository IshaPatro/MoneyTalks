"""Integration tests against the real shipped Northstar AI data
(data/monthly_summary.csv, data/transactions.csv) -- 3 years of real
CSV rows, not a hand-crafted fixture. This is what proves the engine
works end to end on the actual demo dataset, not just a toy example.
"""

from pathlib import Path

import pytest

from backend.finance_engine.engine import FinanceEngine

REPO_ROOT = Path(__file__).resolve().parents[3]
SUMMARY_CSV = REPO_ROOT / "data" / "monthly_summary.csv"
TRANSACTIONS_CSV = REPO_ROOT / "data" / "transactions.csv"

pytestmark = pytest.mark.skipif(
    not SUMMARY_CSV.exists() or not TRANSACTIONS_CSV.exists(),
    reason="demo dataset not present",
)


@pytest.fixture(scope="module")
def engine() -> FinanceEngine:
    return FinanceEngine.from_csv(SUMMARY_CSV, TRANSACTIONS_CSV)


def test_dataset_loads_with_expected_shape(engine: FinanceEngine):
    info = engine.load_dataset_info()
    assert info["transaction_count"] > 30000
    assert "2025-09" in info["periods"]
    assert set(info["available_dimensions"]) >= {"customer", "vendor"}
    assert "Subscription Revenue" in info["accounts"]


def test_compare_periods_known_subscription_revenue_jump(engine: FinanceEngine):
    variances = {v.account: v for v in engine.compare_periods("2025-09", "2025-08")}
    sub_rev = variances["Subscription Revenue"]
    # Verified against a pandas pivot of the raw CSV (see conversation):
    # 2025-08 -> 2025-09 subscription revenue rose ~27.7%.
    assert sub_rev.change == pytest.approx(439513.53, abs=1.0)
    assert sub_rev.change_pct == pytest.approx(27.7, abs=0.1)


def test_rank_variances_surfaces_subscription_revenue_first(engine: FinanceEngine):
    ranked = engine.rank_variances("2025-09", "2025-08", top_n=5)
    assert ranked[0].account == "Subscription Revenue"
    assert "Payroll" in [v.account for v in ranked[:2]]


def test_breakdown_by_customer_sums_to_total_change(engine: FinanceEngine):
    variances = {v.account: v for v in engine.compare_periods("2025-09", "2025-08")}
    sub_rev = variances["Subscription Revenue"]

    drivers = engine.breakdown_variance(sub_rev.variance_id, dimension="customer")
    assert drivers
    total_driver_change = sum(d.change for d in drivers)
    assert total_driver_change == pytest.approx(sub_rev.change, abs=1.0)

    # Named (non-"Other") drivers should each carry real supporting txns.
    named = [d for d in drivers if d.entity != "Other"]
    assert named
    for d in named:
        assert d.transaction_ids


def test_get_top_transactions_are_real_rows_for_top_driver(engine: FinanceEngine):
    variances = {v.account: v for v in engine.compare_periods("2025-09", "2025-08")}
    sub_rev = variances["Subscription Revenue"]
    drivers = engine.breakdown_variance(sub_rev.variance_id, dimension="customer")
    top_driver = max((d for d in drivers if d.entity != "Other"), key=lambda d: abs(d.change))

    txns = engine.get_top_transactions(sub_rev.variance_id, entity=top_driver.entity, limit=5)
    assert txns
    assert all(t.customer == top_driver.entity for t in txns)
    assert all(t.account == "Subscription Revenue" for t in txns)


def test_legal_one_off_expense_appears_and_has_a_vendor_driver(engine: FinanceEngine):
    """Mirrors the README's 'one-off expense' demo scenario: Legal &
    Professional goes from 0 in August to a real spend in September."""
    variances = {v.account: v for v in engine.compare_periods("2025-09", "2025-08")}
    legal = variances["Legal & Professional"]
    assert legal.previous == 0
    assert legal.current != 0

    drivers = engine.breakdown_variance(legal.variance_id, dimension="vendor")
    assert drivers
    assert any(d.transaction_ids for d in drivers)


def test_historical_changes_over_real_multi_year_data(engine: FinanceEngine):
    history = engine.get_historical_account_changes("Subscription Revenue", periods=12)
    assert len(history) == 12
    periods = [h["period"] for h in history]
    assert periods == sorted(periods)  # chronological order
    # the Sept 2025 spike should stand out from the rest of the year
    sept = next(h for h in history if h["period"] == "2025-09")
    others = [h["change_pct"] for h in history if h["period"] != "2025-09"]
    assert sept["change_pct"] > max(others)


def test_all_variances_are_valid_pydantic_objects(engine: FinanceEngine):
    """Every Variance/Driver/Transaction produced from the real dataset
    must satisfy the shared contract schema -- this is what guarantees
    Role 2 can consume it without any adaptation."""
    for variance in engine.rank_variances("2025-09", "2025-08", top_n=10):
        assert variance.variance_id
        drivers = engine.breakdown_variance(variance.variance_id)
        for driver in drivers:
            assert driver.driver_id
            assert driver.dimension
        txns = engine.get_top_transactions(variance.variance_id, limit=3)
        for txn in txns:
            assert txn.transaction_id
            assert txn.account == variance.account
