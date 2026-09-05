"""Validates VarianceCard / build_dashboard against the real subscription
dataset -- this is the concrete frontend contract (see
backend/contracts/FRONTEND_DATA_REFERENCE.md).
"""

from pathlib import Path

import pytest

from backend.finance_engine.engine import FinanceEngine
from backend.integration.dashboard import build_dashboard
from backend.memory.store import MemoryStore


def test_dashboard_returns_ranked_material_cards(engine: FinanceEngine, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cards = build_dashboard(engine, "2025-10", "2025-09", top_n=5)

    assert len(cards) == 5
    assert [c.rank for c in cards] == [1, 2, 3, 4, 5]
    assert cards[0].account == "ACC-0001"


def test_whale_card_has_full_evidence(engine: FinanceEngine, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cards = build_dashboard(engine, "2025-10", "2025-09", top_n=1)
    card = cards[0]

    assert card.primary_driver is not None
    assert card.primary_driver.entity == "Expansion"
    assert card.top_transactions
    assert card.transaction_ids


def test_card_json_serializes_cleanly(engine: FinanceEngine, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cards = build_dashboard(engine, "2025-10", "2025-09", top_n=3)
    for card in cards:
        payload = card.to_dict()
        assert payload["variance_id"] == card.variance_id
        assert isinstance(payload["driver_summary"], str)


def test_card_surfaces_confirmed_memory(tmp_path: Path, engine: FinanceEngine, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    memory = MemoryStore(tmp_path / "memory.db")
    memory.save_confirmed_context(
        account="ACC-0001", period="2025-10",
        explanation="One-time plan upgrade, not expected to recur.",
    )

    # top_n large enough to guarantee ACC-0001 is included regardless of
    # how it ranks that month -- this test is about memory, not ranking.
    cards = build_dashboard(engine, "2025-11", "2025-10", memory=memory, top_n=70)
    card = next(c for c in cards if c.account == "ACC-0001")

    assert card.confirmed_context is not None
    assert "One-time plan upgrade" in card.confirmed_context.explanation


def test_historical_trend_present(engine: FinanceEngine, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cards = build_dashboard(engine, "2025-10", "2025-09", top_n=1)
    card = cards[0]
    assert card.historical_trend
