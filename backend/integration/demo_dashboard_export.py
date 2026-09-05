"""Prints/exports the REAL VarianceCard JSON the frontend should build
against, using the real Northstar AI dataset -- so Person 3 doesn't have
to reverse-engineer the shape from whyledger_frontend_reference_full.csv
(which assumes a different, subscription-billing data model; see
backend/contracts/FRONTEND_DATA_REFERENCE.md).

Run directly:

    python3 -m backend.integration.demo_dashboard_export

Writes backend/integration/sample_dashboard.json.
"""

from __future__ import annotations

import json
from pathlib import Path

from backend.finance_engine.engine import FinanceEngine
from backend.integration.dashboard import build_dashboard
from backend.memory.store import MemoryStore

REPO_ROOT = Path(__file__).resolve().parents[2]
SUMMARY_CSV = REPO_ROOT / "data" / "monthly_summary.csv"
TRANSACTIONS_CSV = REPO_ROOT / "data" / "transactions.csv"
OUTPUT_PATH = Path(__file__).resolve().parent / "sample_dashboard.json"


def main() -> None:
    engine = FinanceEngine.from_csv(SUMMARY_CSV, TRANSACTIONS_CSV)
    memory = MemoryStore(REPO_ROOT / "backend" / "memory" / "demo_export.db")

    cards = build_dashboard(engine, "2025-09", "2025-08", memory=memory, top_n=5)
    payload = [c.to_dict() for c in cards]

    OUTPUT_PATH.write_text(json.dumps(payload, indent=2, default=str))
    print(f"Wrote {len(payload)} cards to {OUTPUT_PATH}")

    print()
    print("Preview:")
    for c in cards:
        print(f"  #{c.rank} {c.account:<24} {c.change:>+12,.0f}  {c.change_pct:>+7.1f}%  -> {c.headline}")


if __name__ == "__main__":
    main()
