"""End-to-end demo of the full pipeline against the real synthetic
subscription dataset (data/subscription_accounts.csv).

Run directly:

    python3 -m backend.finance_engine.demo_pipeline

Walks through README section 22's Integration Test using the seeded demo
scenarios: a whale expansion masking portfolio-wide fragility, an SLA
credit one-off, and multi-run memory.
"""

from __future__ import annotations

from pathlib import Path

from backend.finance_engine.engine import FinanceEngine, PORTFOLIO_ACCOUNT_NAME
from backend.agent_engine.investigate import investigate_variance
from backend.agent_engine.narrative_check import verify_narrative_claim
from backend.memory.store import MemoryStore

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_CSV = REPO_ROOT / "data" / "subscription_accounts.csv"


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

    print("2. PORTFOLIO HEADLINE: 2025-09 -> 2025-10")
    _line()
    portfolio = engine.get_portfolio_variance("2025-10", "2025-09")
    print(f"Total Portfolio MRR: {portfolio.previous:,.0f} -> {portfolio.current:,.0f}  "
          f"({portfolio.change:+,.0f}, {portfolio.change_pct:+.1f}%)")
    print()

    print("3. WHO ACTUALLY DROVE IT: breakdown by account")
    _line()
    account_drivers = engine.breakdown_variance(portfolio.variance_id, dimension="account", top_n=5)
    for d in account_drivers:
        print(f"  {d.entity:<12} {d.change:>+12,.0f}")
    whale_share = abs(account_drivers[0].change) / abs(portfolio.change) * 100
    print(f"\n  -> the #1 account alone is {whale_share:.0f}% of the net portfolio change.")
    print()

    print("4. AND BY SEGMENT")
    _line()
    for d in engine.breakdown_variance(portfolio.variance_id, dimension="company_size"):
        print(f"  {d.entity:<12} {d.change:>+12,.0f}")
    print()

    whale_id = account_drivers[0].entity
    variances = {v.account: v for v in engine.compare_periods("2025-10", "2025-09")}
    whale = variances[whale_id]

    print(f"5. INVESTIGATE THE TOP ACCOUNT: {whale_id}")
    _line()
    explanation = investigate_variance(whale, engine, period="2025-10", memory=memory)
    print(explanation.headline)
    print(explanation.explanation)
    print(f"Evidence: {len(explanation.driver_ids)} driver(s), {len(explanation.transaction_ids)} transaction(s)")
    print()

    print("6. CONFIRM + STORE MEMORY")
    _line()
    memory.save_confirmed_context(
        account=whale_id, period="2025-10",
        explanation="Large one-time plan upgrade, not expected to recur every month.",
    )
    print("Saved.")
    print()

    print("7. ANALYZE NEXT PERIOD, REUSE MEMORY")
    _line()
    next_variances = {v.account: v for v in engine.compare_periods("2025-11", "2025-10")}
    next_whale = next_variances.get(whale_id)
    if next_whale:
        next_explanation = investigate_variance(next_whale, engine, period="2025-11", memory=memory)
        print(next_explanation.headline)
        print(next_explanation.explanation)
        print(f"Historical context retrieved: {next_explanation.historical_context}")
    print()

    print("8. OPTIONAL: NARRATIVE FACT-CHECK ON THE PORTFOLIO HEADLINE")
    _line()
    claim = "Portfolio MRR growth this quarter was broad-based across the customer base."
    verdict = verify_narrative_claim(claim, portfolio, engine)
    print(f'Claim: "{claim}"')
    print(f"Verdict: {verdict.verdict.upper()}")
    print(f"Why: {verdict.reasoning}")


if __name__ == "__main__":
    main()
