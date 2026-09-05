"""Shared fixtures for finance_engine tests.

`spec_example_engine` reproduces the exact worked example from the
project README (Enterprise Revenue $820k -> $1,080,000, Acme/Globex/
Umbrella/Hooli/Other driver breakdown, and the same ranking order as the
spec's rank_variances() example) so the engine's output can be checked
against hand-verifiable numbers, not just "it ran without crashing".
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from backend.finance_engine.engine import FinanceEngine

# account -> (july_amount, august_amount)
# Chosen so change / change_pct exactly reproduce the README's
# compare_periods()/rank_variances() example.
SPEC_SUMMARY = {
    "Enterprise Revenue": (820000, 1080000),
    "SMB Revenue": (574000, 532000),
    "Payroll": (593000, 647000),
    "Cloud Infrastructure": (251773.05, 322773.05),
}

# customer -> (july_amount, august_amount) for Enterprise Revenue only.
# Deltas reproduce the README's breakdown_variance() example exactly:
# Acme +53k, Globex +44k, Umbrella +33k, Hooli +22k, Other +108k.
# The "Other" bucket is spread across several small customers (18k change
# each) rather than one big one, since a single entity bigger than Hooli
# would legitimately outrank it for a named driver slot -- "Other" is a
# residual of many small movements, not one disguised whale.
SPEC_CUSTOMERS = {
    "Acme": (100000, 153000),
    "Globex": (90000, 134000),
    "Umbrella": (80000, 113000),
    "Hooli": (70000, 92000),
    "OtherCust1": (80000, 98000),
    "OtherCust2": (80000, 98000),
    "OtherCust3": (80000, 98000),
    "OtherCust4": (80000, 98000),
    "OtherCust5": (80000, 98000),
    "OtherCust6": (80000, 98000),
}


def _write_summary_csv(path: Path) -> None:
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["period", "account", "amount"])
        for account, (july, august) in SPEC_SUMMARY.items():
            writer.writerow(["2026-07", account, july])
            writer.writerow(["2026-08", account, august])


def _write_transactions_csv(path: Path) -> None:
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["transaction_id", "date", "period", "account", "amount", "customer"])
        tx_id = 0
        for customer, (july, august) in SPEC_CUSTOMERS.items():
            for period, amount, date in [
                ("2026-07", july, "2026-07-15"),
                ("2026-08", august, "2026-08-15"),
            ]:
                tx_id += 1
                # split into two transactions per period so get_top_transactions
                # has more than one row to sort/limit.
                writer.writerow([f"TX{tx_id:04d}A", date, period, "Enterprise Revenue", amount * 0.6, customer])
                writer.writerow([f"TX{tx_id:04d}B", date, period, "Enterprise Revenue", amount * 0.4, customer])


@pytest.fixture()
def spec_example_engine(tmp_path: Path) -> FinanceEngine:
    summary_path = tmp_path / "summary.csv"
    transactions_path = tmp_path / "transactions.csv"
    _write_summary_csv(summary_path)
    _write_transactions_csv(transactions_path)
    return FinanceEngine.from_csv(summary_path, transactions_path)
