from backend.memory.store import MemoryStore


def test_save_and_retrieve_confirmed_context(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    store.save_confirmed_context(
        account="Sales Commissions", period="2026-03",
        explanation="Quarter-end commission payments.",
    )
    store.save_confirmed_context(
        account="Sales Commissions", period="2026-06",
        explanation="Quarter-end commission payments.",
    )

    results = store.get_previous_context("Sales Commissions", period="2026-09")
    assert len(results) == 2
    assert results[0].period == "2026-06"  # most recent first
    assert results[1].period == "2026-03"


def test_get_previous_context_only_returns_earlier_periods(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    store.save_confirmed_context(
        account="Sales Commissions", period="2026-09",
        explanation="Should not appear when querying same period.",
    )
    results = store.get_previous_context("Sales Commissions", period="2026-09")
    assert results == []


def test_get_previous_context_filters_by_account(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    store.save_confirmed_context(
        account="Sales Commissions", period="2026-03", explanation="Commission note."
    )
    store.save_confirmed_context(
        account="Legal", period="2026-03", explanation="One-off invoice."
    )
    results = store.get_previous_context("Legal", period="2026-09")
    assert len(results) == 1
    assert results[0].account == "Legal"


def test_corrected_explanation_is_saved_as_new_confirmed_record(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    store.save_confirmed_context(
        account="Legal", period="2026-03", explanation="Quarter-end commissions."
    )
    # user corrects it
    store.save_confirmed_context(
        account="Legal", period="2026-03", explanation="This was an annual renewal."
    )
    results = store.get_previous_context("Legal", period="2026-09")
    explanations = {r.explanation for r in results}
    assert "This was an annual renewal." in explanations


def test_entity_filter(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    store.save_confirmed_context(
        account="Enterprise Revenue", period="2026-03",
        explanation="Acme expansion.", entity="Acme",
    )
    store.save_confirmed_context(
        account="Enterprise Revenue", period="2026-03",
        explanation="Globex new contract.", entity="Globex",
    )
    results = store.get_previous_context(
        "Enterprise Revenue", period="2026-09", entity="Acme"
    )
    assert len(results) == 1
    assert results[0].entity == "Acme"
