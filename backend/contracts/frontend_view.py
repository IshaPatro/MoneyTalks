"""The real, demo-ready frontend contract.

`whyledger_frontend_reference_full.csv` (a wide per-customer-account/month
reference someone handed to the frontend dev) assumes a subscription-billing
data model (MRR, seat expansions, churn, SLA credits) our general-ledger
dataset doesn't have. See FRONTEND_DATA_REFERENCE.md for the field-by-field
reconciliation. `VarianceCard` below is the equivalent concept built only
from data this backend can actually produce -- one flattened, self-contained
object per variance, combining Role 1's numbers and Role 2's narrative so
the frontend never has to stitch together three separate API calls or
infer anything implicitly.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from backend.contracts.schemas import ConfirmedContextRef, Driver, Explanation, Transaction, Variance


class DriverView(BaseModel):
    driver_id: str
    dimension: str
    entity: str
    change: float
    share_pct: float  # this driver's change as a % of the total variance change


class VarianceCard(BaseModel):
    """Everything the Overview and Investigation screens (README section 15)
    need for one variance, already assembled server-side."""

    variance_id: str
    account: str
    rank: int
    is_material: bool

    previous: float
    current: float
    change: float
    change_pct: float
    direction: str  # "increase" | "decrease"

    primary_driver: Optional[DriverView] = None
    secondary_driver: Optional[DriverView] = None
    other_drivers: list[DriverView] = Field(default_factory=list)
    driver_summary: str  # e.g. "Acme +53.0k; Globex +44.0k; Other +130.0k"

    top_transactions: list[Transaction] = Field(default_factory=list)

    headline: str
    explanation: str
    evidence_summary: str  # e.g. "3 drivers, 5 supporting transactions"
    driver_ids: list[str] = Field(default_factory=list)
    transaction_ids: list[str] = Field(default_factory=list)

    historical_trend: list[dict] = Field(default_factory=list)  # [{period, change, change_pct}]
    change_vs_recent_avg_label: Optional[str] = None  # e.g. "5.2x the recent average"

    confirmed_context: Optional[ConfirmedContextRef] = None

    def to_dict(self) -> dict:
        return self.model_dump()


def _driver_view(driver: Driver, total_change: float) -> DriverView:
    share = (driver.change / total_change * 100) if total_change else 0.0
    return DriverView(
        driver_id=driver.driver_id, dimension=driver.dimension,
        entity=driver.entity, change=driver.change, share_pct=share,
    )


def _driver_summary(drivers: list[Driver]) -> str:
    return "; ".join(f"{d.entity} {d.change:+,.1f}" for d in drivers) if drivers else "No driver breakdown available."


def _change_vs_recent_avg_label(history: list[dict], latest_change_pct: float) -> Optional[str]:
    prior = history[:-1] if len(history) > 1 else []
    if not prior:
        return None
    avg_pct = sum(abs(h["change_pct"]) for h in prior) / len(prior)
    if avg_pct == 0:
        return None
    ratio = abs(latest_change_pct) / avg_pct
    if ratio >= 1.5:
        return f"{ratio:.1f}x the recent average monthly move"
    if ratio <= 0.67:
        return f"only {ratio:.1f}x the recent average monthly move"
    return "in line with recent monthly movement"


def build_variance_card(
    variance: Variance,
    rank: int,
    drivers: list[Driver],
    top_transactions: list[Transaction],
    explanation: Explanation,
    history: list[dict],
    confirmed_context: Optional[ConfirmedContextRef] = None,
    is_material: bool = True,
) -> VarianceCard:
    """Assemble one VarianceCard from real Role 1 + Role 2 outputs. No
    numbers are invented here -- this only reshapes what's already been
    computed into one object for the frontend."""

    ranked_drivers = sorted(drivers, key=lambda d: abs(d.change), reverse=True)
    driver_views = [_driver_view(d, variance.change) for d in ranked_drivers]

    return VarianceCard(
        variance_id=variance.variance_id,
        account=variance.account,
        rank=rank,
        is_material=is_material,
        previous=variance.previous,
        current=variance.current,
        change=variance.change,
        change_pct=variance.change_pct,
        direction="increase" if variance.change >= 0 else "decrease",
        primary_driver=driver_views[0] if len(driver_views) > 0 else None,
        secondary_driver=driver_views[1] if len(driver_views) > 1 else None,
        other_drivers=driver_views[2:],
        driver_summary=_driver_summary(ranked_drivers),
        top_transactions=top_transactions,
        headline=explanation.headline,
        explanation=explanation.explanation,
        evidence_summary=f"{len(explanation.driver_ids)} driver(s), {len(explanation.transaction_ids)} supporting transaction(s)",
        driver_ids=explanation.driver_ids,
        transaction_ids=explanation.transaction_ids,
        historical_trend=history,
        change_vs_recent_avg_label=_change_vs_recent_avg_label(history, variance.change_pct),
        confirmed_context=confirmed_context,
    )
