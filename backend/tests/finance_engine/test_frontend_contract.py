"""Validates the real frontend contract (VarianceCard / build_dashboard)
against the real dataset -- this is what a frontend dev should be able
to trust instead of the aspirational whyledger_frontend_reference_full.csv.
"""

from pathlib import Path

import pytest

from backend.finance_engine.engine import FinanceEngine
from backend.integration.dashboard import build_dashboard
from backend.memory.store import MemoryStore

REPO_ROOT = Path(__file__).resolve().parents[3]
SUMMARY_CSV = REPO_ROOT / "data" / "monthly_summary.csv"
TRANSACTIONS_CSV = REPO_ROOT / "data" / "transactions.csv"

pytestmark = pytest.mark.skipif(
    not SUMMARY_CSV.exists() or not TRANSACTIONS_CSV.exists(),
    reason="demo dataset not present",
)


@pytest.fixture()
def engine() -> FinanceEngine:
    return FinanceEngine.from_csv(SUMMARY_CSV, TRANSACTIONS_CSV)


def test_dashboard_returns_ranked_material_cards(engine: FinanceEngine, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cards = build_dashboard(engine, "2025-09", "2025-08", top_n=5)

    assert len(cards) == 5
    assert [c.rank for c in cards] == [1, 2, 3, 4, 5]
    assert cards[0].account == "Subscription Revenue"
    assert all(c.is_material for c in cards)


def test_card_never_evidence_free_even_when_other_dominates(engine: FinanceEngine, monkeypatch):
    """Subscription Revenue's growth is broad-based (Other bucket wins),
    but the card must still surface real transactions from named
    customers -- see build_dashboard's evidence_drivers fallback."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cards = build_dashboard(engine, "2025-09", "2025-08", top_n=1)
    card = cards[0]

    assert card.primary_driver is not None
    assert card.top_transactions, "card must have supporting transactions"
    assert card.transaction_ids


def test_card_json_serializes_cleanly(engine: FinanceEngine, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cards = build_dashboard(engine, "2025-09", "2025-08", top_n=2)
    for card in cards:
        payload = card.to_dict()
        assert payload["variance_id"] == card.variance_id
        assert isinstance(payload["driver_summary"], str)


def test_card_surfaces_confirmed_memory(tmp_path: Path, engine: FinanceEngine, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    memory = MemoryStore(tmp_path / "memory.db")
    memory.save_confirmed_context(
        account="Subscription Revenue", period="2025-08",
        explanation="Broad-based growth across many mid-market accounts.",
    )

    cards = build_dashboard(engine, "2025-09", "2025-08", memory=memory, top_n=1)
    card = cards[0]

    assert card.confirmed_context is not None
    assert "Broad-based growth" in card.confirmed_context.explanation
    assert "Broad-based growth" in card.explanation  # narrative actually cites it


def test_historical_trend_and_recent_avg_label_present(engine: FinanceEngine, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cards = build_dashboard(engine, "2025-09", "2025-08", top_n=1)
    card = cards[0]

    assert card.historical_trend
    assert card.change_vs_recent_avg_label is not None
