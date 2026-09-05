"""Interface Role 2 uses to talk to Role 1's analytics engine.

Role 2 never touches CSVs, DuckDB, or does financial arithmetic directly.
Instead it depends on this narrow `AnalyticsEngine` protocol, matching the
public functions Role 1 exposes (README section 10):

    load_dataset()
    compare_periods()
    rank_variances()
    breakdown_variance()
    get_top_transactions()
    get_historical_account_changes()

Until Role 1's real engine is ready, `MockAnalyticsEngine` below implements
the same protocol with canned data so Role 2 can build and test end to end.
Swapping in the real engine later is just: pass a different object that
satisfies `AnalyticsEngine` into `investigate_variance()`.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from backend.contracts.schemas import Driver, Transaction, Variance


@runtime_checkable
class AnalyticsEngine(Protocol):
    def breakdown_variance(self, variance_id: str) -> list[Driver]:
        """Return the driver breakdown (by whatever dimension is available)
        for the given variance."""
        ...

    def get_top_transactions(
        self, variance_id: str, entity: str | None = None, limit: int = 10
    ) -> list[Transaction]:
        """Return supporting transactions, optionally filtered to one
        driver entity."""
        ...

    def get_historical_account_changes(
        self, account: str, periods: int = 6
    ) -> list[dict]:
        """Return recent period-over-period changes for this account, e.g.
        [{"period": "2026-03", "change": 40000, "change_pct": 12.1}, ...]."""
        ...


class MockAnalyticsEngine:
    """Canned Role 1 responses for the Northstar AI demo scenarios.

    Used for Role 2 development/tests before Role 1's real engine lands.
    """

    def __init__(self) -> None:
        self._drivers: dict[str, list[Driver]] = {
            "VAR_001": [
                Driver(
                    driver_id="DRV_001",
                    dimension="customer",
                    entity="Acme",
                    change=53000,
                    transaction_ids=["TX101", "TX102"],
                ),
                Driver(
                    driver_id="DRV_002",
                    dimension="customer",
                    entity="Globex",
                    change=44000,
                    transaction_ids=["TX103"],
                ),
                Driver(
                    driver_id="DRV_003",
                    dimension="customer",
                    entity="Umbrella",
                    change=33000,
                    transaction_ids=["TX104"],
                ),
                Driver(
                    driver_id="DRV_004",
                    dimension="customer",
                    entity="Other",
                    change=130000,
                    transaction_ids=[],
                ),
            ],
            "VAR_002": [
                Driver(
                    driver_id="DRV_010",
                    dimension="vendor",
                    entity="Cravath & Co",
                    change=85000,
                    transaction_ids=["TX201"],
                ),
            ],
            "VAR_003": [
                Driver(
                    driver_id="DRV_020",
                    dimension="department",
                    entity="Sales",
                    change=42000,
                    transaction_ids=["TX301", "TX302"],
                ),
            ],
        }
        self._transactions: dict[str, Transaction] = {
            "TX101": Transaction(
                transaction_id="TX101", date="2026-08-03", period="2026-08",
                account="Enterprise Revenue", amount=30000, customer="Acme",
                description="Acme - contract expansion",
            ),
            "TX102": Transaction(
                transaction_id="TX102", date="2026-08-18", period="2026-08",
                account="Enterprise Revenue", amount=23000, customer="Acme",
                description="Acme - additional seats",
            ),
            "TX103": Transaction(
                transaction_id="TX103", date="2026-08-10", period="2026-08",
                account="Enterprise Revenue", amount=44000, customer="Globex",
                description="Globex - new contract",
            ),
            "TX104": Transaction(
                transaction_id="TX104", date="2026-08-22", period="2026-08",
                account="Enterprise Revenue", amount=33000, customer="Umbrella",
                description="Umbrella - renewal upsell",
            ),
            "TX201": Transaction(
                transaction_id="TX201", date="2026-08-15", period="2026-08",
                account="Legal", amount=-85000, vendor="Cravath & Co",
                description="Cravath & Co - litigation invoice",
            ),
            "TX301": Transaction(
                transaction_id="TX301", date="2026-09-30", period="2026-09",
                account="Sales Commissions", amount=-25000, department="Sales",
                description="Quarter-end commission payout",
            ),
            "TX302": Transaction(
                transaction_id="TX302", date="2026-09-30", period="2026-09",
                account="Sales Commissions", amount=-17000, department="Sales",
                description="Quarter-end commission payout",
            ),
        }
        self._history: dict[str, list[dict]] = {
            "Sales Commissions": [
                {"period": "2026-03", "change": 38000, "change_pct": 41.2},
                {"period": "2026-06", "change": 40500, "change_pct": 43.0},
            ],
            "Enterprise Revenue": [
                {"period": "2026-05", "change": 90000, "change_pct": 14.0},
            ],
        }

    def breakdown_variance(self, variance_id: str) -> list[Driver]:
        return self._drivers.get(variance_id, [])

    def get_top_transactions(
        self, variance_id: str, entity: str | None = None, limit: int = 10
    ) -> list[Transaction]:
        drivers = self._drivers.get(variance_id, [])
        wanted_ids: set[str] = set()
        for d in drivers:
            if entity is None or d.entity == entity:
                wanted_ids.update(d.transaction_ids)
        txns = [self._transactions[tid] for tid in wanted_ids if tid in self._transactions]
        return txns[:limit]

    def get_historical_account_changes(
        self, account: str, periods: int = 6
    ) -> list[dict]:
        return self._history.get(account, [])[-periods:]


MOCK_VARIANCES: dict[str, Variance] = {
    "VAR_001": Variance(
        variance_id="VAR_001", account="Enterprise Revenue",
        previous=820000, current=1080000, change=260000, change_pct=31.7,
    ),
    "VAR_002": Variance(
        variance_id="VAR_002", account="Legal",
        previous=15000, current=100000, change=85000, change_pct=566.7,
    ),
    "VAR_003": Variance(
        variance_id="VAR_003", account="Sales Commissions",
        previous=58000, current=100000, change=42000, change_pct=72.4,
    ),
}
