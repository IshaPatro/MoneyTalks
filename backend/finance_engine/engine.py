"""Role 1: the financial analytics engine.

Computes real financial facts -- period comparisons, ranked variances,
dimensional driver breakdowns, supporting transactions, and simple
historical trends -- and returns them as the shared contract objects in
`backend.contracts.schemas` (Variance / Driver / Transaction). No prose,
no LLM calls: everything here is arithmetic over the ingested CSVs.

`FinanceEngine`'s public methods are named to match the functions the
project spec asks Role 1 to expose (load_dataset, compare_periods,
rank_variances, breakdown_variance, get_top_transactions,
get_historical_account_changes), and its method signatures for
breakdown_variance/get_top_transactions/get_historical_account_changes
match the `AnalyticsEngine` protocol Role 2 already codes against
(backend/agent_engine/analytics_interface.py) -- so an instance of this
class is a drop-in replacement for `MockAnalyticsEngine` with no changes
needed on the Role 2 side.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import pandas as pd

from backend.contracts.schemas import Driver, Transaction, Variance
from backend.finance_engine.ingestion import (
    OPTIONAL_DIMENSIONS,
    FinanceDataset,
    load_dataset,
)

# How many named drivers to return per breakdown before folding the rest
# into an "Other" bucket.
DEFAULT_TOP_DRIVERS = 4

# Ranking weights for rank_variances(): absolute dollar movement is
# weighted higher than percentage movement so a huge-percentage swing in a
# tiny account doesn't outrank a smaller-percentage swing in a major one.
ABS_CHANGE_WEIGHT = 0.65
PCT_CHANGE_WEIGHT = 0.35
# Percentage moves are capped before being normalized into the score, so
# a near-zero-base account (e.g. a brand-new line item) with a
# mathematically enormous % change doesn't dominate the ranking.
PCT_CHANGE_CAP = 200.0


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", str(text)).strip("_").upper()


def _pct_change(change: float, base: float) -> float:
    """Percentage change relative to |base|. A brand-new line item (base
    == 0) is reported as +/-100% rather than an undefined/infinite value."""
    if base == 0:
        if change == 0:
            return 0.0
        return 100.0 if change > 0 else -100.0
    return (change / abs(base)) * 100.0


class FinanceEngine:
    def __init__(self, dataset: FinanceDataset) -> None:
        self.dataset = dataset
        # variance_id -> (account, comparison_period, current_period)
        self._variance_index: dict[str, tuple[str, str, str]] = {}
        # variance_id -> dimension used for its most recent breakdown
        self._variance_dimension: dict[str, str] = {}

    @classmethod
    def from_csv(
        cls, summary_path: str | Path, transactions_path: Optional[str | Path] = None
    ) -> "FinanceEngine":
        return cls(load_dataset(summary_path, transactions_path))

    # ------------------------------------------------------------------
    # 1. load_dataset
    # ------------------------------------------------------------------
    def load_dataset_info(self) -> dict:
        """Metadata about the ingested dataset (periods, dimensions, etc).
        Named `_info` to avoid clashing with the module-level
        `ingestion.load_dataset` used to build the engine; both satisfy
        the spec's "load_dataset()" requirement at their own layer."""
        return self.dataset.info()

    # ------------------------------------------------------------------
    # 2. compare_periods
    # ------------------------------------------------------------------
    def compare_periods(self, current_period: str, comparison_period: str) -> list[Variance]:
        summary = self.dataset.summary
        cur = summary[summary["period"] == current_period].set_index("account")["amount"]
        prev = summary[summary["period"] == comparison_period].set_index("account")["amount"]

        accounts = sorted(set(cur.index) | set(prev.index))
        variances: list[Variance] = []
        for account in accounts:
            previous_amount = float(prev.get(account, 0.0))
            current_amount = float(cur.get(account, 0.0))
            change = current_amount - previous_amount
            change_pct = _pct_change(change, previous_amount)

            variance_id = self._variance_id(account, comparison_period, current_period)
            self._variance_index[variance_id] = (account, comparison_period, current_period)

            variances.append(
                Variance(
                    variance_id=variance_id,
                    account=account,
                    previous=previous_amount,
                    current=current_amount,
                    change=change,
                    change_pct=change_pct,
                )
            )
        return variances

    # ------------------------------------------------------------------
    # 3. rank_variances
    # ------------------------------------------------------------------
    def rank_variances(
        self, current_period: str, comparison_period: str, top_n: int = 10
    ) -> list[Variance]:
        variances = self.compare_periods(current_period, comparison_period)
        if not variances:
            return []

        max_abs_change = max((abs(v.change) for v in variances), default=0.0) or 1.0
        max_abs_pct = max(
            (min(abs(v.change_pct), PCT_CHANGE_CAP) for v in variances), default=0.0
        ) or 1.0

        def score(v: Variance) -> float:
            norm_abs = abs(v.change) / max_abs_change
            norm_pct = min(abs(v.change_pct), PCT_CHANGE_CAP) / max_abs_pct
            return ABS_CHANGE_WEIGHT * norm_abs + PCT_CHANGE_WEIGHT * norm_pct

        ranked = sorted(variances, key=score, reverse=True)
        return ranked[:top_n]

    # ------------------------------------------------------------------
    # 4. breakdown_variance
    # ------------------------------------------------------------------
    def breakdown_variance(
        self,
        variance_id: str,
        dimension: Optional[str] = None,
        top_n: int = DEFAULT_TOP_DRIVERS,
    ) -> list[Driver]:
        if variance_id not in self._variance_index:
            raise KeyError(f"Unknown variance_id: {variance_id!r}. Call compare_periods/rank_variances first.")
        account, comparison_period, current_period = self._variance_index[variance_id]

        txns = self.dataset.transactions
        if txns.empty:
            return []
        account_txns = txns[txns["account"] == account]
        period_txns = account_txns[account_txns["period"].isin([comparison_period, current_period])]

        if dimension is None:
            dimension = self._auto_dimension(period_txns)
        if dimension is None or dimension not in period_txns.columns:
            return []

        self._variance_dimension[variance_id] = dimension

        cur = account_txns[account_txns["period"] == current_period]
        prev = account_txns[account_txns["period"] == comparison_period]
        cur_by_entity = cur.groupby(dimension)["amount"].sum()
        prev_by_entity = prev.groupby(dimension)["amount"].sum()

        entities = sorted(
            e for e in set(cur_by_entity.index) | set(prev_by_entity.index) if pd.notna(e)
        )
        rows = []
        for entity in entities:
            current_amount = float(cur_by_entity.get(entity, 0.0))
            previous_amount = float(prev_by_entity.get(entity, 0.0))
            rows.append((entity, current_amount - previous_amount))

        rows.sort(key=lambda t: abs(t[1]), reverse=True)
        top_rows, rest_rows = rows[:top_n], rows[top_n:]

        drivers: list[Driver] = []
        for entity, change in top_rows:
            driver_id = self._driver_id(account, dimension, entity, current_period)
            transaction_ids = self._transaction_ids_for(
                account, dimension, entity, current_period, comparison_period
            )
            drivers.append(
                Driver(
                    driver_id=driver_id,
                    dimension=dimension,
                    entity=str(entity),
                    change=change,
                    transaction_ids=transaction_ids,
                )
            )

        if rest_rows:
            other_change = sum(change for _, change in rest_rows)
            driver_id = self._driver_id(account, dimension, "Other", current_period)
            drivers.append(
                Driver(
                    driver_id=driver_id,
                    dimension=dimension,
                    entity="Other",
                    change=other_change,
                    transaction_ids=[],
                )
            )

        return drivers

    def _auto_dimension(self, sub_df: pd.DataFrame) -> Optional[str]:
        for dim in OPTIONAL_DIMENSIONS:
            if dim in sub_df.columns and sub_df[dim].notna().any():
                return dim
        return None

    # ------------------------------------------------------------------
    # 5. get_top_transactions
    # ------------------------------------------------------------------
    def get_top_transactions(
        self, variance_id: str, entity: Optional[str] = None, limit: int = 10
    ) -> list[Transaction]:
        if variance_id not in self._variance_index:
            raise KeyError(f"Unknown variance_id: {variance_id!r}. Call compare_periods/rank_variances first.")
        account, comparison_period, current_period = self._variance_index[variance_id]
        dimension = self._variance_dimension.get(variance_id)

        txns = self.dataset.transactions
        sub = txns[txns["account"] == account]
        if entity is not None and dimension is not None and dimension in sub.columns:
            sub = sub[sub[dimension] == entity]

        current_rows = sub[sub["period"] == current_period]
        pool = current_rows if not current_rows.empty else sub[sub["period"] == comparison_period]
        if pool.empty:
            return []

        pool = pool.reindex(pool["amount"].abs().sort_values(ascending=False).index).head(limit)
        return [self._row_to_transaction(row) for _, row in pool.iterrows()]

    def _transaction_ids_for(
        self, account: str, dimension: str, entity, current_period: str, comparison_period: str
    ) -> list[str]:
        txns = self.dataset.transactions
        mask = (txns["account"] == account) & (txns[dimension] == entity)
        current_rows = txns[mask & (txns["period"] == current_period)]
        pool = current_rows if not current_rows.empty else txns[mask & (txns["period"] == comparison_period)]
        return pool["transaction_id"].tolist()

    @staticmethod
    def _row_to_transaction(row: pd.Series) -> Transaction:
        def _opt(col: str) -> Optional[str]:
            value = row.get(col)
            return None if value is None or pd.isna(value) else str(value)

        return Transaction(
            transaction_id=str(row["transaction_id"]),
            date=str(row["date"]),
            period=str(row["period"]),
            account=str(row["account"]),
            amount=float(row["amount"]),
            description=_opt("description"),
            customer=_opt("customer"),
            vendor=_opt("vendor"),
            product=_opt("product"),
            department=_opt("department"),
            region=_opt("region"),
        )

    # ------------------------------------------------------------------
    # 6. get_historical_account_changes
    # ------------------------------------------------------------------
    def get_historical_account_changes(self, account: str, periods: int = 6) -> list[dict]:
        history = (
            self.dataset.summary[self.dataset.summary["account"] == account]
            .sort_values("period")
            .reset_index(drop=True)
        )
        results: list[dict] = []
        for i in range(1, len(history)):
            prev_amount = float(history.loc[i - 1, "amount"])
            cur_amount = float(history.loc[i, "amount"])
            change = cur_amount - prev_amount
            results.append(
                {
                    "period": str(history.loc[i, "period"]),
                    "change": change,
                    "change_pct": _pct_change(change, prev_amount),
                }
            )
        return results[-periods:]

    # ------------------------------------------------------------------
    # id helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _variance_id(account: str, comparison_period: str, current_period: str) -> str:
        return f"VAR_{_slug(account)}_{_slug(comparison_period)}_{_slug(current_period)}"

    @staticmethod
    def _driver_id(account: str, dimension: str, entity, current_period: str) -> str:
        return f"DRV_{_slug(account)}_{_slug(dimension)}_{_slug(entity)}_{_slug(current_period)}"
