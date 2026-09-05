import csv
from pathlib import Path

import pytest

from backend.finance_engine.engine import FinanceEngine

# Reproduces the README's get_historical_account_changes() example:
# April +3%, May +5%, June +4%, July +6%, August +31%.
MONTHLY_PCT = [3, 5, 4, 6, 31]


@pytest.fixture()
def history_engine(tmp_path: Path) -> FinanceEngine:
    path = tmp_path / "summary.csv"
    amount = 100000.0
    rows = [("2026-03", "Enterprise Revenue", amount)]
    period_names = ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08"]
    for period, pct in zip(period_names, MONTHLY_PCT):
        amount = amount * (1 + pct / 100)
        rows.append((period, "Enterprise Revenue", amount))

    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["period", "account", "amount"])
        writer.writerows(rows)

    return FinanceEngine.from_csv(path)


def test_historical_changes_match_expected_pct(history_engine: FinanceEngine):
    history = history_engine.get_historical_account_changes("Enterprise Revenue", periods=6)
    assert [h["period"] for h in history] == ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08"]
    pct_values = [h["change_pct"] for h in history]
    assert pct_values == pytest.approx(MONTHLY_PCT, abs=0.01)


def test_historical_changes_respects_periods_limit(history_engine: FinanceEngine):
    history = history_engine.get_historical_account_changes("Enterprise Revenue", periods=2)
    assert len(history) == 2
    assert [h["period"] for h in history] == ["2026-07", "2026-08"]


def test_historical_changes_unknown_account_returns_empty(history_engine: FinanceEngine):
    assert history_engine.get_historical_account_changes("Nonexistent Account") == []


def test_last_period_is_a_much_bigger_jump_than_recent_history(history_engine: FinanceEngine):
    """This is the exact insight Role 2's explanation should be able to
    surface: 'this increase is substantially larger than recent monthly
    movements.'"""
    history = history_engine.get_historical_account_changes("Enterprise Revenue", periods=6)
    recent = history[:-1]
    latest = history[-1]
    avg_recent_pct = sum(h["change_pct"] for h in recent) / len(recent)
    assert latest["change_pct"] > avg_recent_pct * 5
