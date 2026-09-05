import csv
from pathlib import Path

import pytest

from backend.finance_engine.ingestion import DatasetValidationError, load_dataset


def _write(path: Path, header: list[str], rows: list[list]) -> None:
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


def test_load_generic_schema(tmp_path: Path):
    summary_path = tmp_path / "summary.csv"
    txn_path = tmp_path / "transactions.csv"
    _write(summary_path, ["period", "account", "amount"], [["2026-01", "Revenue", 1000]])
    _write(
        txn_path,
        ["transaction_id", "date", "period", "account", "amount", "customer"],
        [["TX1", "2026-01-05", "2026-01", "Revenue", 1000, "Acme"]],
    )

    dataset = load_dataset(summary_path, txn_path)
    assert dataset.periods == ["2026-01"]
    assert dataset.accounts == ["Revenue"]
    assert "customer" in dataset.available_dimensions
    assert "vendor" not in dataset.available_dimensions


def test_load_demo_schema_aliases(tmp_path: Path):
    """The shipped Northstar AI CSVs use account_name/amount_usd/txn_id/
    txn_date/counterparty_* instead of the generic column names -- the
    loader must transparently handle both."""
    summary_path = tmp_path / "summary.csv"
    txn_path = tmp_path / "transactions.csv"
    _write(
        summary_path,
        ["period", "account_code", "account_name", "account_type", "amount_usd", "txn_count"],
        [["2026-01", 4000, "Subscription Revenue", "revenue", 500000, 100]],
    )
    _write(
        txn_path,
        [
            "txn_id", "txn_date", "period", "account_name", "amount_usd",
            "counterparty_type", "counterparty_name",
        ],
        [
            ["E1", "2026-01-02", "2026-01", "Subscription Revenue", 5000, "customer", "Acme"],
            ["E2", "2026-01-02", "2026-01", "Subscription Revenue", -2000, "vendor", "AWS"],
        ],
    )

    dataset = load_dataset(summary_path, txn_path)
    assert dataset.accounts == ["Subscription Revenue"]
    assert set(dataset.available_dimensions) >= {"customer", "vendor"}
    assert dataset.transactions.loc[dataset.transactions["transaction_id"] == "E1", "customer"].iloc[0] == "Acme"
    assert dataset.transactions.loc[dataset.transactions["transaction_id"] == "E2", "vendor"].iloc[0] == "AWS"


def test_missing_required_column_raises(tmp_path: Path):
    summary_path = tmp_path / "summary.csv"
    _write(summary_path, ["period", "amount"], [["2026-01", 1000]])  # missing 'account'

    with pytest.raises(DatasetValidationError):
        load_dataset(summary_path)


def test_summary_only_dataset_works_without_transactions(tmp_path: Path):
    summary_path = tmp_path / "summary.csv"
    _write(summary_path, ["period", "account", "amount"], [["2026-01", "Revenue", 1000]])

    dataset = load_dataset(summary_path)
    assert dataset.transactions.empty
    assert dataset.available_dimensions == []
