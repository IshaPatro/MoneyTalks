"""End-to-end demo of the full pipeline against the real synthetic
subscription dataset (data/subscription_accounts.csv).

Run directly:

    python3 -m backend.finance_engine.demo_pipeline

Walks through README section 22's Integration Test using the flagship
scenario in this dataset: portfolio MRR looks like it's down slightly one
month, and drilling in reveals the entire decline is one customer's churn
-- not broad market softness. Also demonstrates multi-run memory and the
narrative fact-check catching an overstated "broad-based" claim.
"""

from __future__ import annotations

from pathlib import Path

from backend.finance_engine.engine import FinanceEngine, PORTFOLIO_ACCOUNT_NAME
from backend.agent_engine.investigate import investigate_variance
from backend.agent_engine.narrative_check import verify_narrative_claim
from backend.memory.store import MemoryStore

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_CSV = REPO_ROOT / "data" / "subscription_accounts.csv"

CURRENT_PERIOD = "2026-09"
COMPARISON_PERIOD = "2026-08"
NEXT_PERIOD = "2026-10"


def _line(char: str = "-", n: int = 72) -> None:
    print(char * n)


def main() -> None:
    engine = FinanceEngine.from_csv(DATA_CSV)
    memory = MemoryStore(REPO_ROOT / "backend" / "memory" / "demo_pipeline.db")

    info = engine.load_dataset_info()
    print("1. UPLOAD")
    _line()
    print(f"Loaded {info['account_count']} customer accounts, {info['transaction_count']} transactions")
    print(f"Available breakdown dimensions: {info['available_dimensions']}")
    print()

    print(f"2. PORTFOLIO HEADLINE: {COMPARISON_PERIOD} -> {CURRENT_PERIOD}")
    _line()
    portfolio = engine.get_portfolio_variance(CURRENT_PERIOD, COMPARISON_PERIOD)
    print(f"Total Portfolio MRR: {portfolio.previous:,.0f} -> {portfolio.current:,.0f}  "
          f"({portfolio.change:+,.0f}, {portfolio.change_pct:+.1f}%)")
    print()

    print("3. WHO ACTUALLY DROVE IT: breakdown by account")
    _line()
    account_drivers = engine.breakdown_variance(portfolio.variance_id, dimension="account", top_n=5)
    for d in account_drivers:
        print(f"  {d.entity:<12} {d.change:>+12,.0f}")
    top_driver = account_drivers[0]
    top_share = abs(top_driver.change) / abs(portfolio.change) * 100
    print(f"\n  -> {top_driver.entity} alone is {top_share:.0f}% of the net portfolio change.")
    print()

    print("4. AND BY INDUSTRY")
    _line()
    for d in engine.breakdown_variance(portfolio.variance_id, dimension="industry", top_n=5):
        print(f"  {d.entity:<15} {d.change:>+12,.0f}")
    print()

    top_account_id = top_driver.entity
    variances = {v.account: v for v in engine.compare_periods(CURRENT_PERIOD, COMPARISON_PERIOD)}
    top_variance = variances[top_account_id]

    print(f"5. INVESTIGATE THE TOP ACCOUNT: {top_account_id}")
    _line()
    explanation = investigate_variance(top_variance, engine, period=CURRENT_PERIOD, memory=memory)
    print(explanation.headline)
    print(explanation.explanation)
    print(f"Evidence: {len(explanation.driver_ids)} driver(s), {len(explanation.transaction_ids)} transaction(s)")
    print()

    print("6/7. MULTI-RUN MEMORY: a recurring pattern, confirmed once, recognized again")
    _line()
    # ACC-0019 has a genuine recurring pattern -- a small contraction every
    # 3 months (contract renewal cycle) -- unlike the one-time churn above,
    # which is exactly what memory is for: confirm the explanation once,
    # then recognize the SAME pattern automatically next time it recurs.
    recurring_account = "ACC-0019"
    memory.save_confirmed_context(
        account=recurring_account, period="2026-05",
        explanation="Quarterly contract renewal renegotiation -- recurring, not a red flag.",
    )
    print(f"Run 1 ({recurring_account}, 2026-05): confirmed as a recurring renewal pattern.")

    next_variances = {v.account: v for v in engine.compare_periods("2026-08", "2026-07")}
    recurring_variance = next_variances.get(recurring_account)
    if recurring_variance:
        recurring_explanation = investigate_variance(recurring_variance, engine, period="2026-08", memory=memory)
        print(f"\nRun 2 ({recurring_account}, 2026-08): {recurring_explanation.headline}")
        print(recurring_explanation.explanation)
        print(f"Historical context retrieved: {recurring_explanation.historical_context}")
    print()

    print("8. OPTIONAL: NARRATIVE FACT-CHECK ON THE PORTFOLIO HEADLINE")
    _line()
    claim = "Revenue was down this month due to broad-based softness across the customer base."
    verdict = verify_narrative_claim(claim, portfolio, engine)
    print(f'Claim: "{claim}"')
    print(f"Verdict: {verdict.verdict.upper()}")
    print(f"Why: {verdict.reasoning}")


if __name__ == "__main__":
    main()
