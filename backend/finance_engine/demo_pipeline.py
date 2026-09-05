"""End-to-end demo of the full pipeline against the REAL Northstar AI
dataset (data/monthly_summary.csv, data/transactions.csv) -- not mocks.

Run directly:

    python3 -m backend.finance_engine.demo_pipeline

Walks through exactly the flow in README section 22 (Integration Test):
upload -> compare periods -> rank variances -> drill into the top one ->
show drivers/transactions -> generate an explanation -> confirm it into
memory -> analyze the next period -> reuse the confirmed context ->
run the optional narrative fact-check.
"""

from __future__ import annotations

from pathlib import Path

from backend.finance_engine.engine import FinanceEngine
from backend.agent_engine.investigate import investigate_variance
from backend.agent_engine.narrative_check import verify_narrative_claim
from backend.memory.store import MemoryStore

REPO_ROOT = Path(__file__).resolve().parents[2]
SUMMARY_CSV = REPO_ROOT / "data" / "monthly_summary.csv"
TRANSACTIONS_CSV = REPO_ROOT / "data" / "transactions.csv"


def _line(char: str = "-", n: int = 72) -> None:
    print(char * n)


def main() -> None:
    engine = FinanceEngine.from_csv(SUMMARY_CSV, TRANSACTIONS_CSV)
    memory = MemoryStore(REPO_ROOT / "backend" / "memory" / "demo_pipeline.db")

    info = engine.load_dataset_info()
    print("1. UPLOAD")
    _line()
    print(f"Loaded {info['transaction_count']:,} transactions across {len(info['periods'])} periods")
    print(f"Available dimensions: {info['available_dimensions']}")
    print()

    print("2. COMPARE PERIODS: 2025-08 -> 2025-09")
    _line()
    ranked = engine.rank_variances("2025-09", "2025-08", top_n=5)
    for i, v in enumerate(ranked, 1):
        print(f"{i}. {v.account:<24} {v.change:>+12,.0f}   {v.change_pct:>+7.1f}%")
    print()

    top = ranked[0]
    print(f"3. INVESTIGATE TOP VARIANCE: {top.account}")
    _line()
    drivers = engine.breakdown_variance(top.variance_id, dimension="customer")
    for d in drivers:
        print(f"  {d.entity:<24} {d.change:>+12,.0f}")
    print()

    explanation = investigate_variance(top, engine, period="2025-09", memory=memory)
    print("4. AI EXPLANATION")
    _line()
    print(explanation.headline)
    print(explanation.explanation)
    print(f"Evidence: {len(explanation.driver_ids)} drivers, {len(explanation.transaction_ids)} transactions")
    print()

    print("5. CONFIRM + STORE MEMORY (simulating user clicking 'Yes, correct')")
    _line()
    memory.save_confirmed_context(
        account=top.account, period="2025-09",
        explanation="Broad-based growth across many mid-market and SMB accounts, not one whale customer.",
    )
    print("Saved.")
    print()

    print("6. ANALYZE NEXT PERIOD: 2025-09 -> 2025-10, REUSE MEMORY")
    _line()
    next_variances = {v.account: v for v in engine.compare_periods("2025-10", "2025-09")}
    next_top = next_variances[top.account]
    next_explanation = investigate_variance(next_top, engine, period="2025-10", memory=memory)
    print(next_explanation.headline)
    print(next_explanation.explanation)
    print(f"Historical context retrieved: {next_explanation.historical_context}")
    print()

    print("7. OPTIONAL: NARRATIVE FACT-CHECK")
    _line()
    claim = f"Growth was driven by a single major new enterprise customer this quarter."
    verdict = verify_narrative_claim(claim, top, engine)
    print(f'Claim: "{claim}"')
    print(f"Verdict: {verdict.verdict.upper()}")
    print(f"Why: {verdict.reasoning}")


if __name__ == "__main__":
    main()
