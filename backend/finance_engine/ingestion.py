"""CSV ingestion for the finance engine (Role 1).

Reads a monthly summary CSV and a transaction-level CSV, normalizes them
into two pandas DataFrames with a fixed internal column set, and figures
out which optional dimensions (customer, vendor, product, region, ...)
are actually present in this dataset so the rest of the engine can adapt.

Required summary columns:  period, account, amount
Required transaction columns: transaction_id, date, period, account, amount

The Northstar AI demo CSVs (data/monthly_summary.csv, data/transactions.csv)
use different header names (account_name, amount_usd, txn_id, txn_date,
counterparty_name/counterparty_type, ...); `_COLUMN_ALIASES` maps those
onto the internal names so both the generic schema and the shipped demo
data work without special-casing the demo file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd

REQUIRED_SUMMARY_COLUMNS = {"period", "account", "amount"}
REQUIRED_TRANSACTION_COLUMNS = {"transaction_id", "date", "period", "account", "amount"}

# Optional dimensions the engine will use if present, in priority order
# (used when a caller doesn't specify which dimension to break down by).
OPTIONAL_DIMENSIONS = [
    "customer", "vendor", "product", "department", "region",
    "segment", "industry", "plan_tier",
]

# Maps alternate header names (as seen in the shipped Northstar AI CSVs)
# onto the internal canonical names above.
_SUMMARY_ALIASES = {
    "account_name": "account",
    "amount_usd": "amount",
}
_TRANSACTION_ALIASES = {
    "txn_id": "transaction_id",
    "txn_date": "date",
    "account_name": "account",
    "amount_usd": "amount",
    "memo": "description",
}


class DatasetValidationError(ValueError):
    pass


def _rename_known_aliases(df: pd.DataFrame, aliases: dict) -> pd.DataFrame:
    """Rename alias columns onto their canonical names. If the canonical
    name already exists on the frame (e.g. the demo CSV has both a raw
    `amount` and an `amount_usd` column), drop the pre-existing one first
    -- the aliased column is the authoritative one -- so the rename can't
    produce two columns sharing the same name."""
    applicable = {k: v for k, v in aliases.items() if k in df.columns}
    collisions = [v for v in applicable.values() if v in df.columns]
    if collisions:
        df = df.drop(columns=collisions)
    return df.rename(columns=applicable)


def _split_counterparty(df: pd.DataFrame) -> pd.DataFrame:
    """The demo transactions CSV stores customer/vendor in a single
    counterparty_name column tagged by counterparty_type. Split it into
    separate customer/vendor columns so both act as normal optional
    dimensions."""
    if "counterparty_name" not in df.columns or "counterparty_type" not in df.columns:
        return df
    if "customer" not in df.columns:
        df["customer"] = df["counterparty_name"].where(df["counterparty_type"] == "customer")
    if "vendor" not in df.columns:
        df["vendor"] = df["counterparty_name"].where(df["counterparty_type"] == "vendor")
    return df


@dataclass
class FinanceDataset:
    summary: pd.DataFrame
    transactions: pd.DataFrame
    periods: list[str] = field(default_factory=list)
    available_dimensions: list[str] = field(default_factory=list)
    accounts: list[str] = field(default_factory=list)

    def info(self) -> dict:
        return {
            "periods": self.periods,
            "transaction_count": int(len(self.transactions)),
            "available_dimensions": self.available_dimensions,
            "accounts": self.accounts,
        }


def _validate_columns(df: pd.DataFrame, required: set[str], kind: str) -> None:
    missing = required - set(df.columns)
    if missing:
        raise DatasetValidationError(
            f"{kind} CSV is missing required column(s): {sorted(missing)}"
        )


def load_dataset(
    summary_path: str | Path,
    transactions_path: Optional[str | Path] = None,
) -> FinanceDataset:
    """Load and normalize the summary CSV (required) and transactions CSV
    (optional -- drill-down features need it, but period comparison alone
    can run off the summary file)."""

    summary = pd.read_csv(summary_path)
    summary = _rename_known_aliases(summary, _SUMMARY_ALIASES)
    _validate_columns(summary, REQUIRED_SUMMARY_COLUMNS, "Summary")
    summary["period"] = summary["period"].astype(str)
    # Normalize to unsigned dollar magnitude: some ledgers record expenses
    # as negative amounts, but every downstream contract (Variance.change,
    # Driver.change) treats "increase" as "this account's dollar size grew"
    # regardless of whether it's revenue or an expense -- so a bigger
    # invoice must always read as a positive change, never a more-negative
    # one. See engine.py's compare_periods/breakdown_variance.
    summary["amount"] = summary["amount"].astype(float).abs()

    if transactions_path is not None:
        transactions = pd.read_csv(transactions_path)
        transactions = _rename_known_aliases(transactions, _TRANSACTION_ALIASES)
        transactions = _split_counterparty(transactions)
        _validate_columns(transactions, REQUIRED_TRANSACTION_COLUMNS, "Transactions")
        transactions["period"] = transactions["period"].astype(str)
        transactions["amount"] = transactions["amount"].astype(float).abs()
    else:
        transactions = pd.DataFrame(
            columns=list(REQUIRED_TRANSACTION_COLUMNS) + OPTIONAL_DIMENSIONS
        )

    available_dimensions = [
        dim for dim in OPTIONAL_DIMENSIONS
        if dim in transactions.columns and transactions[dim].notna().any()
    ]

    periods = sorted(set(summary["period"]) | set(transactions["period"]))
    accounts = sorted(set(summary["account"]))

    return FinanceDataset(
        summary=summary,
        transactions=transactions,
        periods=periods,
        available_dimensions=available_dimensions,
        accounts=accounts,
    )
