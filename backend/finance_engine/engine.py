"""Role 1: the financial analytics engine, subscription-billing schema.

Computes real financial facts -- period comparisons, ranked variances,
driver breakdowns (by billing-event category for one account, or by
account/segment for the whole portfolio), supporting transactions, and
historical trends -- from data/subscription_accounts.csv, and returns them
as the shared contract objects in backend.contracts.schemas (Variance /
Driver / Transaction). No prose, no LLM calls: everything here is
arithmetic over the ingested CSV.

Two levels of variance, both using the same Variance/Driver contracts:
  - Account-level: one customer account's own MRR change, broken down by
    billing-event category (new ARR, expansion, contraction, churn, SLA
    credit, refund, usage overage) -- rank_variances() operates here,
    mirroring "which accounts moved the most."
  - Portfolio-level (`get_portfolio_variance`): total MRR change across
    every account, broken down by account (which customers drove it -- the
    "whale vs. broad-based" concentration story) or by segment
    (company_size / industry / contract_type).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import pandas as pd

from backend.contracts.schemas import Driver, Transaction, Variance
from backend.finance_engine.ingestion import (
    BILLING_CATEGORIES,
    SEGMENT_DIMENSIONS,
    SubscriptionDataset,
    load_dataset,
    month_to_period,
    period_to_month,
)

PORTFOLIO_ACCOUNT_NAME = "Total Portfolio MRR"

DEFAULT_TOP_DRIVERS = 4
ABS_CHANGE_WEIGHT = 0.65
PCT_CHANGE_WEIGHT = 0.35
PCT_CHANGE_CAP = 300.0


def _slug(text) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", str(text)).strip("_").upper()


def _pct_change(change: float, base: float) -> float:
    if base == 0:
        if change == 0:
            return 0.0
        return 100.0 if change > 0 else -100.0
    return (change / abs(base)) * 100.0


class FinanceEngine:
    def __init__(self, dataset: SubscriptionDataset) -> None:
        self.dataset = dataset
        self._df = dataset.accounts_df
        # variance_id -> context dict (see _account_variance_id/_portfolio_variance_id)
        self._variance_index: dict[str, dict] = {}

    @classmethod
    def from_csv(cls, path: str | Path) -> "FinanceEngine":
        return cls(load_dataset(path))

    # ------------------------------------------------------------------
    # 1. load_dataset
    # ------------------------------------------------------------------
    def load_dataset_info(self) -> dict:
        return self.dataset.info()

    # ------------------------------------------------------------------
    # 2. compare_periods -- one Variance per customer account
    # ------------------------------------------------------------------
    def compare_periods(self, current_period: str, comparison_period: str) -> list[Variance]:
        current_month = period_to_month(current_period)
        comparison_month = period_to_month(comparison_period)

        cur = self._df[self._df["month"] == current_month].set_index("account_id")["current_mrr"]
        prev = self._df[self._df["month"] == comparison_month].set_index("account_id")["current_mrr"]

        account_ids = sorted(set(cur.index) | set(prev.index))
        variances: list[Variance] = []
        for account_id in account_ids:
            previous_amount = float(prev.get(account_id, 0.0))
            current_amount = float(cur.get(account_id, 0.0))
            change = current_amount - previous_amount
            change_pct = _pct_change(change, previous_amount)

            variance_id = self._account_variance_id(account_id, comparison_period, current_period)
            self._variance_index[variance_id] = {
                "kind": "account", "account_id": account_id,
                "comparison_period": comparison_period, "current_period": current_period,
            }
            variances.append(Variance(
                variance_id=variance_id, account=account_id,
                previous=previous_amount, current=current_amount,
                change=change, change_pct=change_pct,
            ))
        return variances

    def get_portfolio_variance(self, current_period: str, comparison_period: str) -> Variance:
        current_month = period_to_month(current_period)
        comparison_month = period_to_month(comparison_period)
        current_total = float(self._df.loc[self._df["month"] == current_month, "current_mrr"].sum())
        previous_total = float(self._df.loc[self._df["month"] == comparison_month, "current_mrr"].sum())
        change = current_total - previous_total
        change_pct = _pct_change(change, previous_total)

        variance_id = self._portfolio_variance_id(comparison_period, current_period)
        self._variance_index[variance_id] = {
            "kind": "portfolio",
            "comparison_period": comparison_period, "current_period": current_period,
        }
        return Variance(
            variance_id=variance_id, account=PORTFOLIO_ACCOUNT_NAME,
            previous=previous_total, current=current_total,
            change=change, change_pct=change_pct,
        )

    # ------------------------------------------------------------------
    # 3. rank_variances -- ranks customer accounts, not just by percentage
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

        return sorted(variances, key=score, reverse=True)[:top_n]

    # ------------------------------------------------------------------
    # 4. breakdown_variance
    # ------------------------------------------------------------------
    def breakdown_variance(
        self, variance_id: str, dimension: Optional[str] = None, top_n: int = DEFAULT_TOP_DRIVERS,
    ) -> list[Driver]:
        if variance_id not in self._variance_index:
            raise KeyError(f"Unknown variance_id: {variance_id!r}. Call compare_periods/rank_variances/get_portfolio_variance first.")
        ctx = self._variance_index[variance_id]

        if ctx["kind"] == "account":
            return self._breakdown_account(ctx, top_n=top_n)
        return self._breakdown_portfolio(ctx, dimension=dimension, top_n=top_n)

    def _rows_in_range(self, account_id: Optional[str], comparison_period: str, current_period: str) -> pd.DataFrame:
        lo, hi = period_to_month(comparison_period) + 1, period_to_month(current_period)
        mask = (self._df["month"] >= lo) & (self._df["month"] <= hi)
        if account_id is not None:
            mask &= self._df["account_id"] == account_id
        return self._df[mask]

    def _breakdown_account(self, ctx: dict, top_n: int) -> list[Driver]:
        rows = self._rows_in_range(ctx["account_id"], ctx["comparison_period"], ctx["current_period"])
        totals = {cat: float(rows[cat].sum()) for cat in BILLING_CATEGORIES}

        ranked = sorted(
            ((cat, amt) for cat, amt in totals.items() if amt != 0),
            key=lambda kv: abs(kv[1]), reverse=True,
        )
        drivers = []
        for cat, amount in ranked[:top_n]:
            label = cat.replace("_amount", "").replace("_", " ").title().replace(" ", "_")
            transaction_ids = self._category_transaction_ids(rows, cat)
            drivers.append(Driver(
                driver_id=self._driver_id(ctx["account_id"], cat, ctx["current_period"]),
                dimension="billing_category", entity=label, change=amount,
                transaction_ids=transaction_ids,
            ))
        return drivers

    def _category_transaction_ids(self, rows: pd.DataFrame, category_col: str) -> list[str]:
        target_type = category_col.replace("_amount", "").replace("_", " ").title().replace(" ", "_")
        ids: list[str] = []
        for _, row in rows.iterrows():
            for tx_id, tx_type in zip(row["transaction_ids"], row["transaction_types"]):
                if tx_type == target_type:
                    ids.append(tx_id)
        return ids

    def _breakdown_portfolio(self, ctx: dict, dimension: Optional[str], top_n: int) -> list[Driver]:
        dimension = dimension or "account"
        account_variances = self.compare_periods(ctx["current_period"], ctx["comparison_period"])

        if dimension == "account":
            ranked = sorted(account_variances, key=lambda v: abs(v.change), reverse=True)
            top, rest = ranked[:top_n], ranked[top_n:]
            drivers = [
                Driver(
                    driver_id=self._driver_id(v.account, "account", ctx["current_period"]),
                    dimension="account", entity=v.account, change=v.change,
                    transaction_ids=self._account_transaction_ids(v.account, ctx),
                )
                for v in top
            ]
            if rest:
                drivers.append(Driver(
                    driver_id=self._driver_id("OTHER", "account", ctx["current_period"]),
                    dimension="account", entity="Other", change=sum(v.change for v in rest),
                    transaction_ids=[],
                ))
            return drivers

        if dimension not in SEGMENT_DIMENSIONS:
            raise ValueError(f"Unknown breakdown dimension: {dimension!r}. Use 'account' or one of {SEGMENT_DIMENSIONS}.")

        segment_lookup = self._df.drop_duplicates("account_id").set_index("account_id")[dimension]
        totals: dict[str, float] = {}
        for v in account_variances:
            seg_value = segment_lookup.get(v.account, "Unknown")
            totals[seg_value] = totals.get(seg_value, 0.0) + v.change

        ranked = sorted(totals.items(), key=lambda kv: abs(kv[1]), reverse=True)
        return [
            Driver(
                driver_id=self._driver_id(seg_value, dimension, ctx["current_period"]),
                dimension=dimension, entity=str(seg_value), change=change,
                transaction_ids=[],
            )
            for seg_value, change in ranked
        ]

    def _account_transaction_ids(self, account_id: str, ctx: dict) -> list[str]:
        rows = self._rows_in_range(account_id, ctx["comparison_period"], ctx["current_period"])
        return [tid for _, row in rows.iterrows() for tid in row["transaction_ids"]]

    # ------------------------------------------------------------------
    # 5. get_top_transactions
    # ------------------------------------------------------------------
    def get_top_transactions(
        self, variance_id: str, entity: Optional[str] = None, limit: int = 10
    ) -> list[Transaction]:
        if variance_id not in self._variance_index:
            raise KeyError(f"Unknown variance_id: {variance_id!r}. Call compare_periods/rank_variances/get_portfolio_variance first.")
        ctx = self._variance_index[variance_id]

        if ctx["kind"] == "account":
            rows = self._rows_in_range(ctx["account_id"], ctx["comparison_period"], ctx["current_period"])
            target_type = entity if entity in {c.replace("_amount", "").title().replace(" ", "_") for c in BILLING_CATEGORIES} else None
            # normalize e.g. "Sla_Credit" input mismatches by comparing case-insensitively too
            events = self._extract_events(rows)
            if entity is not None:
                events = [e for e in events if e["type"].lower() == entity.lower()]
        else:
            if entity is not None and entity in set(self._df["account_id"]):
                rows = self._rows_in_range(entity, ctx["comparison_period"], ctx["current_period"])
            elif entity is not None:
                seg_col = next((c for c in SEGMENT_DIMENSIONS if entity in set(self._df[c])), None)
                rows = self._rows_in_range(None, ctx["comparison_period"], ctx["current_period"])
                if seg_col is not None:
                    rows = rows[rows[seg_col] == entity]
            else:
                rows = self._rows_in_range(None, ctx["comparison_period"], ctx["current_period"])
            events = self._extract_events(rows)

        events.sort(key=lambda e: abs(e["amount"]), reverse=True)
        return [self._event_to_transaction(e) for e in events[:limit]]

    @staticmethod
    def _extract_events(rows: pd.DataFrame) -> list[dict]:
        events = []
        for _, row in rows.iterrows():
            for tid, ts, ttype, amt, reason in zip(
                row["transaction_ids"], row["transaction_timestamps"],
                row["transaction_types"], row["transaction_amounts"], row["reason_codes"],
            ):
                events.append({
                    "transaction_id": tid, "timestamp": ts, "type": ttype,
                    "amount": float(amt), "reason": reason,
                    "account_id": row["account_id"], "period": row["period"],
                })
        return events

    @staticmethod
    def _event_to_transaction(event: dict) -> Transaction:
        return Transaction(
            transaction_id=event["transaction_id"], date=str(event["timestamp"])[:10],
            period=event["period"], account=event["account_id"], amount=event["amount"],
            description=event["reason"], customer=event["account_id"],
        )

    # ------------------------------------------------------------------
    # 6. get_historical_account_changes
    # ------------------------------------------------------------------
    def get_historical_account_changes(self, account: str, periods: int = 6) -> list[dict]:
        if account == PORTFOLIO_ACCOUNT_NAME:
            series = self._df.groupby("month")["current_mrr"].sum().sort_index()
        else:
            rows = self._df[self._df["account_id"] == account].sort_values("month")
            if rows.empty:
                return []
            series = rows.set_index("month")["current_mrr"]

        results: list[dict] = []
        months = list(series.index)
        for i in range(1, len(months)):
            prev_amount = float(series.iloc[i - 1])
            cur_amount = float(series.iloc[i])
            change = cur_amount - prev_amount
            results.append({
                "period": month_to_period(months[i]),
                "change": change,
                "change_pct": _pct_change(change, prev_amount),
            })
        return results[-periods:]

    # ------------------------------------------------------------------
    # id helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _account_variance_id(account_id: str, comparison_period: str, current_period: str) -> str:
        return f"VAR_{_slug(account_id)}_{_slug(comparison_period)}_{_slug(current_period)}"

    @staticmethod
    def _portfolio_variance_id(comparison_period: str, current_period: str) -> str:
        return f"VAR_PORTFOLIO_{_slug(comparison_period)}_{_slug(current_period)}"

    @staticmethod
    def _driver_id(entity, dimension: str, current_period: str) -> str:
        return f"DRV_{_slug(entity)}_{_slug(dimension)}_{_slug(current_period)}"
