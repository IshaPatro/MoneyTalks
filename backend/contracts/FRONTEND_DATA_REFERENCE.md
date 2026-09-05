# Frontend data reference: what the backend can actually produce

This reconciles `whyledger_frontend_reference_full.csv` (a wide, ~100-column
per-customer-account/month reference someone gave the frontend dev) against
what `backend/finance_engine` + `backend/agent_engine` actually compute
today, from the real `data/monthly_summary.csv` / `data/transactions.csv`.

**Bottom line: the reference file is a different data model, not a superset
of ours.** It's built for a subscription-billing product (per-customer MRR,
seat expansions, churn, SLA credits, usage overage) at one-row-per-customer-
per-month grain. Our data is a general-ledger export (revenue/expense
accounts, broken down by counterparty/vendor/product/region) at
transaction grain, with no per-customer-account MRR lifecycle table. Building
the frontend against the reference file's exact columns would mean wiring up
fields the backend cannot produce from this dataset. Use `VarianceCard`
(`backend/contracts/frontend_view.py`) instead -- it's the equivalent
information, real, and already wired end to end.

## Available now (build the UI against these)

| Reference concept | Real equivalent | Where it comes from |
|---|---|---|
| `current_mrr`, `previous_mrr`, `mrr_change`, `mrr_change_pct` | `Variance.current/previous/change/change_pct` | `FinanceEngine.compare_periods()` |
| `variance_rank`, `material_variance_flag` | `VarianceCard.rank`, `VarianceCard.is_material` | `FinanceEngine.rank_variances()` |
| `primary_driver_*`, `secondary_driver_*` | `VarianceCard.primary_driver` / `.secondary_driver` | `FinanceEngine.breakdown_variance()` |
| `driver_summary` (e.g. "Expansion +13.58; SLA_Credit -3.80") | `VarianceCard.driver_summary` | derived from real `Driver` objects |
| `largest_transaction_*` | `VarianceCard.top_transactions[0]` | `FinanceEngine.get_top_transactions()` |
| `evidence_summary` | `VarianceCard.evidence_summary` + `driver_ids`/`transaction_ids` | `Explanation.driver_ids/transaction_ids` |
| `prior_3m_avg_change_pct`, `change_vs_prior_3m_avg`, `historical_change_label` | `VarianceCard.historical_trend`, `.change_vs_recent_avg_label` | `FinanceEngine.get_historical_account_changes()` |
| `change_direction` | `VarianceCard.direction` ("increase"/"decrease") | derived from `Variance.change` |
| A one-line natural-language narrative | `VarianceCard.headline` / `.explanation` | `generate_explanation()` (Role 2) |
| A confirmed prior explanation surfacing again next period | `VarianceCard.confirmed_context` | `memory.get_previous_context()` |
| Fact-checking a claim about this account against real drivers | separate `NarrativeVerdict` object | `verify_narrative_claim()` (optional feature) |

## Not available with the current dataset (don't build UI that assumes these)

- **Per-customer MRR lifecycle categories**: `new_arr_amount`, `expansion_amount`,
  `contraction_amount`, `churn_amount`, `sla_credit_amount`,
  `usage_overage_amount`, and their `*_share` fields. Our transactions have a
  `txn_kind` (`subscription`, `usage`, `credit_memo`, `one_off`, `annual_commit`, ...)
  but no billing-event taxonomy that maps 1:1 onto these categories, and no
  per-customer MRR waterfall. Faking this from `txn_kind` would misrepresent
  real data as more specific than it is.
- **`churn_flag` / `churn_reason_code`**: would require tracking each
  customer's presence/absence across consecutive periods. Feasible as a
  follow-up (see the "concentration risk" / churn-detection idea already
  discussed), but not implemented.
- **Segment rollups**: `company_size_mrr_change`, `industry_contribution_pct`,
  `contract_type_contribution_pct`. Our transaction data does carry `segment`,
  `industry`, and `plan_tier` columns and these *could* be computed the same
  way `breakdown_variance()` computes customer/vendor breakdowns -- just not
  built yet. Treat as a possible dimension to pass into `breakdown_variance(dimension=...)`.
- **`payment_delay_flag`, `error_rate`, `tickets_count`, `feature_adoption_rate`,
  `active_users`, `usage_growth`**: these are product/support telemetry, not
  financial ledger data. Nothing in `data/*.csv` supports them. Out of scope
  for a finance-ledger tool entirely, not just "not built yet."
- **`next_month_mrr`**: a forecast. Explicitly a non-goal (see README section 4,
  "budget forecasting").
- **`regime_state`, `discount_pct`, `contract_type`**: pricing/contract
  metadata not present in the ledger export.

## Rule for the frontend build

If a UI element needs a field from the "not available" list above, treat it
as **out of scope for this dataset**, not as a bug to report against the
backend -- there's nothing in `data/*.csv` to compute it from. Everything in
the "available now" table is real, tested, and demoed in
`backend/finance_engine/demo_pipeline.py`.
