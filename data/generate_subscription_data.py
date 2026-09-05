"""Generates the real dataset MoneyTalks now runs on: a synthetic but
realistic SaaS subscription-billing dataset matching the exact schema of
whyledger_frontend_reference_full.csv (one row per customer account per
active month, with MRR lifecycle events, product/support telemetry, and
precomputed variance/driver/historical fields).

This supersedes data/monthly_summary.csv + data/transactions.csv as the
backend's real input. Run directly:

    python3 data/generate_subscription_data.py

Writes data/subscription_accounts.csv.

Design notes (why the numbers look the way they do):
- ~70 customer accounts across a 24-month window (2025-01 .. 2026-12),
  staggered signups, SMB/Mid-Market/Enterprise mix with realistic MRR
  bands and churn-rate differences (SMB churns fastest, Enterprise rarely).
- Every derived column (shares, primary/secondary driver, variance score/
  rank, segment rollups, trailing 3-month history, churn_flag, signals) is
  computed the same way backend/finance_engine/engine.py is expected to
  read it, so the generator doubles as a spec for the real derivation
  logic and the two can be cross-checked in tests.
- Seeded scenarios for the demo narrative:
  * ACC-0001 "Vantage Dynamics" (Enterprise): a large one-time seat
    expansion that dominates a single month's portfolio-wide change --
    the "whale" scenario.
  * A cohort of ~15 SMB accounts with broad-based small expansions in the
    same month as the whale -- so that month's growth is NOT actually
    whale-only when you look at the full driver breakdown (concentration-
    risk narrative).
  * ACC-0002 "Meridian Health Systems" (Enterprise): one large one-off
    SLA_Credit from a single outage (mirrors the "one-off expense" demo).
  * A recurring-pattern cohort of Mid-Market accounts with a small
    contraction every 3 months at contract renewal (mirrors the
    "quarter-end commissions" memory demo -- same shape, different label).
"""

from __future__ import annotations

import csv
import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta

random.seed(42)

OUTPUT_PATH = "data/subscription_accounts.csv"

COLUMNS = [
    "account_id", "month", "company_size", "industry", "contract_type",
    "discount_pct", "regime_state", "active_users", "usage_growth",
    "feature_adoption_rate", "error_rate", "tickets_count", "ticket_growth",
    "payment_delay_flag", "current_mrr", "next_month_mrr", "previous_month",
    "previous_mrr", "previous_active_users", "previous_feature_adoption_rate",
    "previous_error_rate", "previous_tickets_count", "previous_discount_pct",
    "mrr_change", "mrr_change_pct", "absolute_mrr_change", "change_direction",
    "active_users_change", "active_users_change_pct", "feature_adoption_change",
    "error_rate_change", "tickets_change", "tickets_change_pct", "discount_change",
    "transaction_id", "timestamp", "transaction_type", "amount", "reason_code",
    "transaction_count", "transaction_ids", "transaction_timestamps",
    "transaction_types", "transaction_amounts", "reason_codes",
    "transaction_amount_total", "transaction_reconciliation_diff",
    "positive_transaction_amount", "negative_transaction_amount",
    "new_arr_amount", "expansion_amount", "contraction_amount", "churn_amount",
    "sla_credit_amount", "refund_amount", "usage_overage_amount",
    "new_arr_share", "expansion_share", "contraction_share", "churn_share",
    "sla_credit_share", "refund_share", "usage_overage_share",
    "largest_transaction_id", "largest_transaction_timestamp",
    "largest_transaction_type", "largest_transaction_amount",
    "largest_transaction_reason_code", "largest_positive_transaction_amount",
    "largest_negative_transaction_amount", "primary_transaction_type",
    "primary_reason_code", "primary_driver_amount", "primary_driver_share",
    "secondary_transaction_type", "secondary_reason_code",
    "secondary_driver_amount", "secondary_driver_share", "change_classification",
    "usage_signal", "adoption_signal", "reliability_signal", "support_signal",
    "payment_signal", "usage_growth_driver_flag", "feature_adoption_driver_flag",
    "error_rate_driver_flag", "ticket_growth_driver_flag",
    "payment_delay_driver_flag", "discount_driver_flag", "variance_score",
    "variance_rank", "material_variance_flag", "account_contribution_to_total_change",
    "account_contribution_pct", "company_size_mrr_change", "company_size_contribution_pct",
    "industry_mrr_change", "industry_contribution_pct", "contract_type_mrr_change",
    "contract_type_contribution_pct", "prior_3m_avg_mrr", "prior_3m_avg_change",
    "prior_3m_avg_change_pct", "prior_3m_max_change", "prior_3m_min_change",
    "change_vs_prior_3m_avg", "historical_change_label", "churn_flag",
    "churn_reason_code", "driver_summary", "evidence_summary",
]

BASE_YEAR, BASE_MONTH = 2025, 1  # global month index 1 == 2025-01
TOTAL_MONTHS = 24

COMPANY_SIZES = ["SMB", "Mid-Market", "Enterprise"]
INDUSTRIES = ["Fintech", "Healthcare", "Retail", "Manufacturing", "Logistics",
              "Energy", "Education", "Media", "Real Estate", "Technology"]
CONTRACT_TYPES = ["Monthly", "Annual", "Multi-Year"]

MRR_BANDS = {"SMB": (300, 2500), "Mid-Market": (2500, 15000), "Enterprise": (15000, 120000)}
MONTHLY_CHURN_PROB = {"SMB": 0.045, "Mid-Market": 0.018, "Enterprise": 0.006}
EXPANSION_PROB = {"SMB": 0.10, "Mid-Market": 0.18, "Enterprise": 0.22}
CONTRACTION_PROB = {"SMB": 0.10, "Mid-Market": 0.07, "Enterprise": 0.04}

COMPANY_NAMES = [
    "Vantage Dynamics", "Meridian Health Systems", "Cobalt Freight", "Brightline Retail",
    "Ashford Manufacturing", "Nimbus Media", "Solace Energy", "Fernwood Realty",
    "Quill Fintech", "Amberline Logistics", "Cascade Learning", "Ironclad Systems",
    "Verity Analytics", "Northgate Foods", "Palisade Robotics", "Wayfarer Travel Tech",
    "Grayson Capital", "Elmwood Clinics", "Tidewater Shipping", "Lumen Broadcasting",
]


def period_label(month_index: int) -> str:
    total = (BASE_MONTH - 1) + (month_index - 1)
    year = BASE_YEAR + total // 12
    month = total % 12 + 1
    return f"{year:02d}-{month:02d}"


def _fmt(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isinf(value):
        return "inf"
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, float):
        return f"{value:.10f}".rstrip("0").rstrip(".") if value != 0 else "0"
    return str(value)


@dataclass
class Transaction:
    transaction_id: str
    timestamp: str
    transaction_type: str
    reason_code: str
    amount: float


CATEGORY_BY_TYPE = {
    "New_ARR": "new_arr_amount", "Expansion": "expansion_amount",
    "Contraction": "contraction_amount", "Churn": "churn_amount",
    "SLA_Credit": "sla_credit_amount", "Refund": "refund_amount",
    "Usage_Overage": "usage_overage_amount",
}
REASON_CODES = {
    "New_ARR": ["New_Logo_Signed"],
    "Expansion": ["Seat_Add", "Feature_Upgrade", "Plan_Upgrade"],
    "Contraction": ["Contract_Downgrade", "Seat_Reduction"],
    "Churn": ["Non_Renewal", "Competitor_Switch", "Budget_Cut"],
    "SLA_Credit": ["System_Outage_Credit", "Performance_SLA_Breach"],
    "Refund": ["Billing_Adjustment", "Duplicate_Charge"],
    "Usage_Overage": ["Usage_Above_Commit"],
}


@dataclass
class Account:
    account_id: str
    name: str
    company_size: str
    industry: str
    contract_type: str
    discount_pct: float
    signup_month: int
    lifetime_months: int
    base_mrr: float
    whale_expansion_month: int | None = None
    sla_shock_month: int | None = None
    quarterly_contraction: bool = False
    # running state
    current_mrr: float = 0.0
    active_users: float = 0.0
    feature_adoption_rate: float = 0.05
    error_rate: float = 0.02
    tickets_count: float = 0.0
    discount_history: dict = field(default_factory=dict)
    churned_at: int | None = None


def _make_accounts() -> list[Account]:
    accounts = []
    for i, name in enumerate(COMPANY_NAMES, start=1):
        size = random.choices(COMPANY_SIZES, weights=[0.45, 0.35, 0.20])[0]
        lo, hi = MRR_BANDS[size]
        acct = Account(
            account_id=f"ACC-{i:04d}",
            name=name,
            company_size=size,
            industry=random.choice(INDUSTRIES),
            contract_type=random.choices(CONTRACT_TYPES, weights=[0.5, 0.35, 0.15])[0],
            discount_pct=round(random.uniform(0.0, 0.20), 4),
            signup_month=random.randint(1, 6),
            lifetime_months=random.randint(14, TOTAL_MONTHS),
            base_mrr=round(random.uniform(lo, hi), 2),
        )
        accounts.append(acct)

    # Seed the demo scenarios explicitly on top of the random roster.
    accounts[0].account_id, accounts[0].name = "ACC-0001", "Vantage Dynamics"
    accounts[0].company_size, accounts[0].industry = "Enterprise", "Technology"
    accounts[0].signup_month = 1
    accounts[0].base_mrr = 42000.0
    accounts[0].whale_expansion_month = 10  # big single-month expansion

    accounts[1].account_id, accounts[1].name = "ACC-0002", "Meridian Health Systems"
    accounts[1].company_size, accounts[1].industry = "Enterprise", "Healthcare"
    accounts[1].signup_month = 1
    accounts[1].base_mrr = 58000.0
    accounts[1].sla_shock_month = 10  # same month as the whale expansion, for contrast

    for acct in accounts[2:17]:  # broad-based small-expansion cohort, same month
        acct.whale_expansion_month = None
        acct.company_size = random.choice(["SMB", "Mid-Market"])

    for acct in accounts[17:24]:
        acct.quarterly_contraction = True
        acct.contract_type = "Annual"

    # Fill out the roster to ~70 accounts by cloning archetypes with new ids/names.
    extra_needed = 70 - len(accounts)
    for j in range(extra_needed):
        base = random.choice(accounts[2:])
        size = random.choices(COMPANY_SIZES, weights=[0.45, 0.35, 0.20])[0]
        lo, hi = MRR_BANDS[size]
        accounts.append(Account(
            account_id=f"ACC-{len(accounts) + 1:04d}",
            name=f"{base.name} Holdings {j + 1}",
            company_size=size,
            industry=random.choice(INDUSTRIES),
            contract_type=random.choices(CONTRACT_TYPES, weights=[0.5, 0.35, 0.15])[0],
            discount_pct=round(random.uniform(0.0, 0.20), 4),
            signup_month=random.randint(1, 18),
            lifetime_months=random.randint(6, TOTAL_MONTHS),
            base_mrr=round(random.uniform(lo, hi), 2),
        ))
    return accounts


def _next_tx_id(counter: dict, kind: str, month_idx: int) -> str:
    key = f"{kind}-{period_label(month_idx)}"
    counter[key] = counter.get(key, 0) + 1
    prefix = "INV" if kind == "invoice" else "CR"
    return f"{prefix}-{period_label(month_idx)}-{counter[key]:03d}"


def _simulate_account(acct: Account, tx_counter: dict) -> list[dict]:
    rows = []
    prev = None  # dict of previous month's snapshot
    month_in_life = 0

    # Accounts run until the dataset's end OR an explicit Churn event fires
    # (never a silent, unexplained disappearance -- every MRR drop to zero
    # must have a real transaction behind it).
    for global_month in range(acct.signup_month, TOTAL_MONTHS + 1):
        month_in_life += 1
        period = period_label(global_month)
        ts_day = random.randint(2, 27)
        base_ts = datetime(int(period[:4]), int(period[5:7]), ts_day, 10, 0, 0)

        events: list[Transaction] = []

        usage_growth = round(random.uniform(-0.06, 0.15), 6)
        payment_delay = random.random() < (0.03 if acct.company_size == "Enterprise" else 0.08)

        if month_in_life == 1:
            acct.current_mrr = acct.base_mrr
            acct.active_users = max(1.0, acct.base_mrr / random.uniform(80, 250))
            events.append(Transaction(
                _next_tx_id(tx_counter, "invoice", global_month), base_ts.isoformat(),
                "New_ARR", "New_Logo_Signed", round(acct.base_mrr, 2),
            ))
        else:
            mrr_before = acct.current_mrr
            terminal_churn = False
            # These correlate the operational telemetry (error_rate,
            # tickets_count) with the billing event it's meant to have
            # caused, so the risk graph (Reliability_Risk -> SLA_Credit_Loss,
            # Support_Friction -> Refund_Loss) has real causal edges to
            # find instead of coincidental, uncorrelated noise.
            reliability_incident = False
            support_incident = False

            # Seeded scenarios take priority over the random walk.
            if acct.whale_expansion_month == month_in_life:
                amt = round(mrr_before * random.uniform(0.55, 0.85), 2)
                events.append(Transaction(_next_tx_id(tx_counter, "invoice", global_month),
                                           base_ts.isoformat(), "Expansion", "Plan_Upgrade", amt))
            elif acct.sla_shock_month == month_in_life:
                amt = -round(mrr_before * random.uniform(0.08, 0.15), 2)
                events.append(Transaction(_next_tx_id(tx_counter, "credit", global_month),
                                           base_ts.isoformat(), "SLA_Credit",
                                           "System_Outage_Credit", amt))
                reliability_incident = True
            elif acct.quarterly_contraction and month_in_life % 3 == 0:
                amt = -round(mrr_before * random.uniform(0.03, 0.08), 2)
                events.append(Transaction(_next_tx_id(tx_counter, "credit", global_month),
                                           base_ts.isoformat(), "Contraction",
                                           "Contract_Downgrade", amt))
            else:
                roll = random.random()
                churn_p = MONTHLY_CHURN_PROB[acct.company_size]
                if month_in_life > 3 and roll < churn_p:
                    terminal_churn = True
                    events.append(Transaction(_next_tx_id(tx_counter, "credit", global_month),
                                               base_ts.isoformat(), "Churn",
                                               random.choice(REASON_CODES["Churn"]), -mrr_before))
                elif roll < churn_p + EXPANSION_PROB[acct.company_size]:
                    amt = round(mrr_before * random.uniform(0.05, 0.35), 2)
                    events.append(Transaction(_next_tx_id(tx_counter, "invoice", global_month),
                                               base_ts.isoformat(), "Expansion",
                                               random.choice(REASON_CODES["Expansion"]), amt))
                    if random.random() < 0.25:
                        amt2 = round(mrr_before * random.uniform(0.01, 0.05), 2)
                        events.append(Transaction(
                            _next_tx_id(tx_counter, "invoice", global_month),
                            (base_ts + timedelta(days=5)).isoformat(), "Usage_Overage",
                            "Usage_Above_Commit", amt2))
                elif roll < churn_p + EXPANSION_PROB[acct.company_size] + CONTRACTION_PROB[acct.company_size]:
                    amt = -round(mrr_before * random.uniform(0.05, 0.25), 2)
                    events.append(Transaction(_next_tx_id(tx_counter, "credit", global_month),
                                               base_ts.isoformat(), "Contraction",
                                               random.choice(REASON_CODES["Contraction"]), amt))
                    if random.random() < 0.3:
                        amt2 = -round(abs(amt) * random.uniform(0.1, 0.3), 2)
                        events.append(Transaction(
                            _next_tx_id(tx_counter, "credit", global_month),
                            (base_ts + timedelta(days=10)).isoformat(), "Refund",
                            "Billing_Adjustment", amt2))
                        support_incident = True
                elif random.random() < 0.05:
                    amt = round(mrr_before * random.uniform(0.01, 0.08), 2)
                    events.append(Transaction(_next_tx_id(tx_counter, "invoice", global_month),
                                               base_ts.isoformat(), "Usage_Overage",
                                               "Usage_Above_Commit", amt))
                # else: a quiet month, no billing events, mrr unchanged.

            total_change = sum(e.amount for e in events)
            acct.current_mrr = 0.0 if terminal_churn else max(0.0, mrr_before + total_change)

            # operational telemetry random-walks a bit
            acct.active_users = max(0.0, acct.active_users + random.uniform(-2, 5)
                                     + (acct.active_users * 0.03 if total_change > 0 else -acct.active_users * 0.02 if total_change < 0 else 0))
            acct.feature_adoption_rate = min(0.98, max(0.0, acct.feature_adoption_rate + random.uniform(-0.01, 0.02)))
            reliability_incident = reliability_incident or random.random() < 0.08
            support_incident = support_incident or random.random() < 0.08
            acct.error_rate = round(max(0.0, min(0.35, (0.08 if reliability_incident else 0.015) + random.uniform(-0.005, 0.01))), 6)
            acct.tickets_count = max(0, round(acct.tickets_count * 0.5 + (random.uniform(2, 6) if support_incident else random.uniform(0, 1.5))))

            if terminal_churn:
                acct.churned_at = global_month

        rows.append({
            "account_id": acct.account_id, "global_month": global_month, "month_in_life": month_in_life,
            "period": period, "company_size": acct.company_size, "industry": acct.industry,
            "contract_type": acct.contract_type, "discount_pct": acct.discount_pct,
            "current_mrr": round(acct.current_mrr, 4), "active_users": round(acct.active_users, 4),
            "feature_adoption_rate": round(acct.feature_adoption_rate, 6),
            "error_rate": round(acct.error_rate, 6), "tickets_count": acct.tickets_count,
            "events": events, "churned": acct.churned_at == global_month,
            "_usage_growth": usage_growth, "_payment_delay": payment_delay,
        })

        if acct.churned_at == global_month:
            break

    return rows


def main() -> None:
    accounts = _make_accounts()
    tx_counter: dict = {}
    all_rows: list[dict] = []
    for acct in accounts:
        all_rows.extend(_simulate_account(acct, tx_counter))

    # ---- second pass: cross-account rollups per calendar period ----
    by_period: dict[str, list[dict]] = {}
    for row in all_rows:
        by_period.setdefault(row["period"], []).append(row)

    by_account: dict[str, list[dict]] = {}
    for row in all_rows:
        by_account.setdefault(row["account_id"], []).append(row)
    for rows in by_account.values():
        rows.sort(key=lambda r: r["global_month"])

    out_rows = []
    for acct_id, rows in by_account.items():
        finalized = []
        for idx, row in enumerate(rows):
            prev_row = rows[idx - 1] if idx > 0 else None
            finalized.append(_finalize_row(row, prev_row, finalized[:idx]))
        for idx, r in enumerate(finalized):
            r["next_month_mrr"] = finalized[idx + 1]["current_mrr"] if idx + 1 < len(finalized) else None
        out_rows.extend(finalized)

    # cross-account scoring needs all rows for a period at once
    period_groups: dict[str, list[dict]] = {}
    for r in out_rows:
        period_groups.setdefault(r["_period"], []).append(r)

    for period, rows in period_groups.items():
        changes = [r["mrr_change"] for r in rows]
        pcts = [r["mrr_change_pct"] for r in rows]
        max_abs_change = max((abs(c) for c in changes), default=0.0) or 1.0
        max_abs_pct = max((min(abs(p), 300.0) for p in pcts), default=0.0) or 1.0
        total_change = sum(changes)

        for r in rows:
            norm_abs = abs(r["mrr_change"]) / max_abs_change
            norm_pct = min(abs(r["mrr_change_pct"]), 300.0) / max_abs_pct
            r["variance_score"] = round(0.65 * norm_abs + 0.35 * norm_pct, 10)

        rows.sort(key=lambda r: r["variance_score"], reverse=True)
        for rank, r in enumerate(rows, start=1):
            r["variance_rank"] = rank
            r["material_variance_flag"] = rank <= max(3, round(len(rows) * 0.1))
            r["account_contribution_to_total_change"] = r["mrr_change"]
            r["account_contribution_pct"] = (r["mrr_change"] / total_change) if total_change else 0.0

        for seg_field, out_change, out_pct in [
            ("company_size", "company_size_mrr_change", "company_size_contribution_pct"),
            ("industry", "industry_mrr_change", "industry_contribution_pct"),
            ("contract_type", "contract_type_mrr_change", "contract_type_contribution_pct"),
        ]:
            seg_totals: dict[str, float] = {}
            for r in rows:
                seg_totals[r[seg_field]] = seg_totals.get(r[seg_field], 0.0) + r["mrr_change"]
            for r in rows:
                seg_change = seg_totals[r[seg_field]]
                r[out_change] = seg_change
                r[out_pct] = (seg_change / total_change) if total_change else 0.0

    # ---- write CSV ----
    with open(OUTPUT_PATH, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(COLUMNS)
        out_rows.sort(key=lambda r: (r["_global_month"], r["account_id"]))
        for r in out_rows:
            writer.writerow([_fmt(r.get(col)) for col in COLUMNS])

    print(f"Wrote {len(out_rows)} rows across {len(by_account)} accounts to {OUTPUT_PATH}")


def _signal(change, pos_thresh, neg_thresh, invert=False) -> str:
    if change is None:
        return "unknown"
    if invert:
        change = -change
    if change > pos_thresh:
        return "positive"
    if change < -neg_thresh:
        return "negative"
    return "stable"


def _finalize_row(row: dict, prev_row: dict | None, history_rows: list[dict]) -> dict:
    events: list[Transaction] = row["events"]
    period = row["period"]
    account_id = row["account_id"]

    previous_mrr = prev_row["current_mrr"] if prev_row else None
    current_mrr = row["current_mrr"]
    mrr_change = (current_mrr - previous_mrr) if previous_mrr is not None else 0.0
    mrr_change_pct = (mrr_change / previous_mrr) if previous_mrr else (1.0 if mrr_change else 0.0)

    prev_users = prev_row["active_users"] if prev_row else None
    active_users_change = (row["active_users"] - prev_users) if prev_users is not None else None
    active_users_change_pct = (active_users_change / prev_users) if prev_users else None

    prev_adopt = prev_row["feature_adoption_rate"] if prev_row else None
    feature_adoption_change = (row["feature_adoption_rate"] - prev_adopt) if prev_adopt is not None else None

    prev_err = prev_row["error_rate"] if prev_row else None
    error_rate_change = (row["error_rate"] - prev_err) if prev_err is not None else None

    prev_tickets = prev_row["tickets_count"] if prev_row else None
    tickets_change = (row["tickets_count"] - prev_tickets) if prev_tickets is not None else None
    if prev_tickets is not None and prev_tickets == 0 and row["tickets_count"] > 0:
        tickets_change_pct = float("inf")
    elif prev_tickets:
        tickets_change_pct = tickets_change / prev_tickets
    else:
        tickets_change_pct = None

    prev_discount = row["discount_pct"]  # discount is stable per account in this generator
    discount_change = 0.0 if prev_row else None

    category_amounts = {c: 0.0 for c in CATEGORY_BY_TYPE.values()}
    for e in events:
        category_amounts[CATEGORY_BY_TYPE[e.transaction_type]] += e.amount

    transaction_amount_total = sum(e.amount for e in events)
    positive_amount = sum(e.amount for e in events if e.amount > 0)
    negative_amount = sum(e.amount for e in events if e.amount < 0)
    reconciliation_diff = round(current_mrr - ((previous_mrr or 0.0) + transaction_amount_total), 6) if previous_mrr is not None else 0.0

    abs_total_for_share = sum(abs(v) for v in category_amounts.values())
    shares = {k: (abs(v) / abs_total_for_share if abs_total_for_share else 0.0) for k, v in category_amounts.items()}

    ranked_categories = sorted(
        ((t, category_amounts[c]) for t, c in CATEGORY_BY_TYPE.items() if category_amounts[c] != 0),
        key=lambda tc: abs(tc[1]), reverse=True,
    )
    primary = ranked_categories[0] if len(ranked_categories) > 0 else None
    secondary = ranked_categories[1] if len(ranked_categories) > 1 else None

    def reason_for(tx_type: str) -> str:
        matches = [e.reason_code for e in events if e.transaction_type == tx_type]
        return matches[0] if matches else ""

    largest_tx = max(events, key=lambda e: abs(e.amount)) if events else None
    largest_positive = max((e.amount for e in events if e.amount > 0), default=0.0)
    largest_negative = min((e.amount for e in events if e.amount < 0), default=0.0)

    if not ranked_categories:
        change_classification = "No_Change"
    elif len(ranked_categories) == 1:
        change_classification = ranked_categories[0][0]
    else:
        top_share = shares[CATEGORY_BY_TYPE[ranked_categories[0][0]]]
        change_classification = ranked_categories[0][0] if top_share >= 0.75 else "Mixed"

    churn_flag = any(e.transaction_type == "Churn" for e in events)
    churn_reason_code = reason_for("Churn") if churn_flag else ""

    prior_window = history_rows[-3:]
    if len(prior_window) < 3:
        prior_3m_avg_mrr = prior_3m_avg_change = prior_3m_avg_change_pct = None
        prior_3m_max_change = prior_3m_min_change = change_vs_prior_3m_avg = None
        historical_change_label = "insufficient_history"
    else:
        prior_mrrs = [r["current_mrr"] for r in prior_window]
        prior_changes = [r["_mrr_change"] for r in prior_window]
        prior_pcts = [r["_mrr_change_pct"] for r in prior_window]
        prior_3m_avg_mrr = sum(prior_mrrs) / 3
        prior_3m_avg_change = sum(prior_changes) / 3
        prior_3m_avg_change_pct = sum(prior_pcts) / 3
        prior_3m_max_change = max(prior_changes)
        prior_3m_min_change = min(prior_changes)
        change_vs_prior_3m_avg = mrr_change - prior_3m_avg_change
        if abs(prior_3m_avg_change) < 1e-6:
            historical_change_label = "normal"
        else:
            ratio = mrr_change / prior_3m_avg_change
            if mrr_change > 0 and ratio > 1.8:
                historical_change_label = "unusual_increase"
            elif mrr_change < 0 and abs(change_vs_prior_3m_avg) > 1.8 * abs(prior_3m_avg_change):
                historical_change_label = "unusual_decrease"
            else:
                historical_change_label = "normal"

    usage_signal = _signal(row.get("_usage_growth", 0.0), 0.02, 0.02)
    adoption_signal = _signal(feature_adoption_change, 0.01, 0.01)
    reliability_signal = _signal(error_rate_change, 0.01, 0.01, invert=True)
    support_signal = _signal(tickets_change if tickets_change != float("inf") else None, 1, 1, invert=True)
    payment_signal = "negative" if row.get("_payment_delay") else "stable"

    driver_summary = "; ".join(f"{t} {amt:+,.4f}" for t, amt in ranked_categories) or "No driver activity this period."
    evidence_summary = f"{len(events)} transactions" + (
        f"; largest {largest_tx.transaction_id} {largest_tx.amount:+,.4f} ({largest_tx.reason_code})" if largest_tx else ""
    )

    result = {
        "_period": period, "_global_month": row["global_month"],
        "_mrr_change": mrr_change, "_mrr_change_pct": mrr_change_pct,
        # "month" is the GLOBAL calendar month index (shared across every
        # account), not a per-account tenure counter -- otherwise two
        # accounts' "month 10" could be different real calendar months and
        # cross-account period comparison would be meaningless. An account
        # simply has no row before its signup month or after it churns.
        "account_id": account_id, "month": row["global_month"],
        "company_size": row["company_size"], "industry": row["industry"],
        "contract_type": row["contract_type"], "discount_pct": row["discount_pct"],
        "regime_state": ("churned" if churn_flag else "growth" if mrr_change > 0
                          else "decline" if mrr_change < 0 else "stable"),
        "active_users": row["active_users"], "usage_growth": row.get("_usage_growth", 0.0),
        "feature_adoption_rate": row["feature_adoption_rate"], "error_rate": row["error_rate"],
        "tickets_count": row["tickets_count"], "ticket_growth": tickets_change_pct,
        "payment_delay_flag": 1 if row.get("_payment_delay") else 0,
        "current_mrr": current_mrr, "next_month_mrr": None,
        "previous_month": (row["global_month"] - 1) if prev_row else None,
        "previous_mrr": previous_mrr, "previous_active_users": prev_users,
        "previous_feature_adoption_rate": prev_adopt, "previous_error_rate": prev_err,
        "previous_tickets_count": prev_tickets, "previous_discount_pct": prev_discount,
        "mrr_change": mrr_change, "mrr_change_pct": mrr_change_pct,
        "absolute_mrr_change": abs(mrr_change),
        "change_direction": "increase" if mrr_change >= 0 else "decrease",
        "active_users_change": active_users_change, "active_users_change_pct": active_users_change_pct,
        "feature_adoption_change": feature_adoption_change, "error_rate_change": error_rate_change,
        "tickets_change": tickets_change, "tickets_change_pct": tickets_change_pct,
        "discount_change": discount_change,
        "transaction_id": events[0].transaction_id if events else "",
        "timestamp": events[0].timestamp if events else "",
        "transaction_type": events[0].transaction_type if events else "",
        "amount": events[0].amount if events else 0.0,
        "reason_code": events[0].reason_code if events else "",
        "transaction_count": len(events),
        "transaction_ids": "[" + ", ".join(f'"{e.transaction_id}"' for e in events) + "]",
        "transaction_timestamps": "[" + ", ".join(f'"{e.timestamp}"' for e in events) + "]",
        "transaction_types": "[" + ", ".join(f'"{e.transaction_type}"' for e in events) + "]",
        "transaction_amounts": "[" + ", ".join(f"{e.amount}" for e in events) + "]",
        "reason_codes": "[" + ", ".join(f'"{e.reason_code}"' for e in events) + "]",
        "transaction_amount_total": transaction_amount_total,
        "transaction_reconciliation_diff": reconciliation_diff,
        "positive_transaction_amount": positive_amount,
        "negative_transaction_amount": negative_amount,
        **category_amounts,
        "new_arr_share": shares["new_arr_amount"], "expansion_share": shares["expansion_amount"],
        "contraction_share": shares["contraction_amount"], "churn_share": shares["churn_amount"],
        "sla_credit_share": shares["sla_credit_amount"], "refund_share": shares["refund_amount"],
        "usage_overage_share": shares["usage_overage_amount"],
        "largest_transaction_id": largest_tx.transaction_id if largest_tx else "",
        "largest_transaction_timestamp": largest_tx.timestamp if largest_tx else "",
        "largest_transaction_type": largest_tx.transaction_type if largest_tx else "",
        "largest_transaction_amount": largest_tx.amount if largest_tx else 0.0,
        "largest_transaction_reason_code": largest_tx.reason_code if largest_tx else "",
        "largest_positive_transaction_amount": largest_positive,
        "largest_negative_transaction_amount": largest_negative,
        "primary_transaction_type": primary[0] if primary else "",
        "primary_reason_code": reason_for(primary[0]) if primary else "",
        "primary_driver_amount": primary[1] if primary else 0.0,
        "primary_driver_share": shares[CATEGORY_BY_TYPE[primary[0]]] if primary else 0.0,
        "secondary_transaction_type": secondary[0] if secondary else "",
        "secondary_reason_code": reason_for(secondary[0]) if secondary else "",
        "secondary_driver_amount": secondary[1] if secondary else 0.0,
        "secondary_driver_share": shares[CATEGORY_BY_TYPE[secondary[0]]] if secondary else 0.0,
        "change_classification": change_classification,
        "usage_signal": usage_signal, "adoption_signal": adoption_signal,
        "reliability_signal": reliability_signal, "support_signal": support_signal,
        "payment_signal": payment_signal,
        "usage_growth_driver_flag": abs(row.get("_usage_growth", 0.0)) > 0.02,
        "feature_adoption_driver_flag": (feature_adoption_change or 0) > 0.01,
        "error_rate_driver_flag": (error_rate_change or 0) > 0.01,
        "ticket_growth_driver_flag": (tickets_change or 0) not in (0, None) and tickets_change != float("inf") and tickets_change > 1,
        "payment_delay_driver_flag": bool(row.get("_payment_delay")),
        "discount_driver_flag": bool(discount_change),
        "variance_score": None, "variance_rank": None, "material_variance_flag": None,
        "account_contribution_to_total_change": None, "account_contribution_pct": None,
        "company_size_mrr_change": None, "company_size_contribution_pct": None,
        "industry_mrr_change": None, "industry_contribution_pct": None,
        "contract_type_mrr_change": None, "contract_type_contribution_pct": None,
        "prior_3m_avg_mrr": prior_3m_avg_mrr, "prior_3m_avg_change": prior_3m_avg_change,
        "prior_3m_avg_change_pct": prior_3m_avg_change_pct, "prior_3m_max_change": prior_3m_max_change,
        "prior_3m_min_change": prior_3m_min_change, "change_vs_prior_3m_avg": change_vs_prior_3m_avg,
        "historical_change_label": historical_change_label,
        "churn_flag": churn_flag, "churn_reason_code": churn_reason_code,
        "driver_summary": driver_summary, "evidence_summary": evidence_summary,
    }
    return result


if __name__ == "__main__":
    main()
