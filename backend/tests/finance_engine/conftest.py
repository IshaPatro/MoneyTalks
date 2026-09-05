from pathlib import Path

import pytest

from backend.finance_engine.engine import FinanceEngine

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_CSV = REPO_ROOT / "data" / "subscription_accounts.csv"


@pytest.fixture(scope="module")
def engine() -> FinanceEngine:
    return FinanceEngine.from_csv(DATA_CSV)
