"""Prints/exports the REAL VarianceCard JSON the frontend should build
against, using the real synthetic subscription dataset
(data/subscription_accounts.csv). See backend/contracts/FRONTEND_DATA_REFERENCE.md
for how this maps onto whyledger_frontend_reference_full.csv.

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
DATA_CSV = REPO_ROOT / "data" / "subscription_accounts.csv"
OUTPUT_PATH = Path(__file__).resolve().parent / "sample_dashboard.json"


def main() -> None:
    engine = FinanceEngine.from_csv(DATA_CSV)
    memory = MemoryStore(REPO_ROOT / "backend" / "memory" / "demo_export.db")

    cards = build_dashboard(engine, "2025-10", "2025-09", memory=memory, top_n=5)
    payload = [c.to_dict() for c in cards]

    OUTPUT_PATH.write_text(json.dumps(payload, indent=2, default=str))
    print(f"Wrote {len(payload)} cards to {OUTPUT_PATH}")

    print()
    print("Preview:")
    for c in cards:
        print(f"  #{c.rank} {c.account:<12} {c.change:>+12,.0f}  {c.change_pct:>+7.1f}%  -> {c.headline}")


if __name__ == "__main__":
    main()
