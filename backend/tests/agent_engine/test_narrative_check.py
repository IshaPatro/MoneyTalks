from backend.agent_engine.analytics_interface import MOCK_VARIANCES, MockAnalyticsEngine
from backend.agent_engine.narrative_check import verify_narrative_claim


def test_supported_claim_matches_named_drivers(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    analytics = MockAnalyticsEngine()
    variance = MOCK_VARIANCES["VAR_001"]  # Enterprise Revenue +260k

    verdict = verify_narrative_claim(
        "Revenue growth was driven by strong momentum with Acme, Globex, and Umbrella.",
        variance, analytics,
    )

    assert verdict.verdict == "supported"
    assert set(verdict.claimed_entities) == {"Acme", "Globex", "Umbrella"}
    assert verdict.match_pct is not None and verdict.match_pct >= 0.5
    assert verdict.driver_ids
    assert verdict.transaction_ids


def test_partially_supported_claim_names_a_minor_driver(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    analytics = MockAnalyticsEngine()
    variance = MOCK_VARIANCES["VAR_001"]

    verdict = verify_narrative_claim(
        "The increase was driven by our new customer Umbrella.", variance, analytics,
    )

    assert verdict.verdict in ("partially_supported", "unsupported")
    assert verdict.claimed_entities == ["Umbrella"]
    assert verdict.match_pct == 33000 / 260000


def test_unverifiable_claim_names_no_known_entity(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    analytics = MockAnalyticsEngine()
    variance = MOCK_VARIANCES["VAR_001"]

    verdict = verify_narrative_claim(
        "Revenue growth reflects strong momentum across the business.",
        variance, analytics,
    )

    assert verdict.verdict == "unverifiable"
    assert verdict.claimed_entities == []
    assert verdict.match_pct is None


def test_broad_based_claim_checked_via_concentration_even_with_no_named_entity(monkeypatch):
    """'broad-based' is a checkable claim on its own: does any single
    entity actually dominate the change? This is the concentration-risk
    check -- see backend/agent_engine/narrative_check.py."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    analytics = MockAnalyticsEngine()
    variance = MOCK_VARIANCES["VAR_001"]  # largest driver ("Other") is 50% of the change

    verdict = verify_narrative_claim(
        "Revenue growth was broad-based across the customer base.", variance, analytics,
    )

    assert verdict.claimed_entities == []  # claim named nobody
    assert verdict.verdict == "supported"  # no single entity exceeds the concentration threshold


def test_broad_based_claim_contradicted_when_one_entity_dominates(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    analytics = MockAnalyticsEngine()
    variance = MOCK_VARIANCES["VAR_002"]  # Legal: single vendor is 100% of the change

    verdict = verify_narrative_claim(
        "The expense increase was broad-based across many vendors.", variance, analytics,
    )

    assert verdict.verdict == "contradicted"
    assert "Cravath & Co" in verdict.matched_entities


def test_contradicted_claim_wrong_direction(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    analytics = MockAnalyticsEngine()
    variance = MOCK_VARIANCES["VAR_001"]  # this account actually increased

    verdict = verify_narrative_claim(
        "Enterprise revenue declined due to softer demand from Acme.",
        variance, analytics,
    )

    assert verdict.verdict == "contradicted"


def test_legal_one_off_claim_supported(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    analytics = MockAnalyticsEngine()
    variance = MOCK_VARIANCES["VAR_002"]  # Legal one-off expense

    verdict = verify_narrative_claim(
        "Legal expense increased due to a one-time invoice from Cravath & Co.",
        variance, analytics,
    )

    assert verdict.verdict == "supported"
    assert verdict.claimed_entities == ["Cravath & Co"]


def test_flat_claim_contradicted_by_large_spike(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    analytics = MockAnalyticsEngine()
    variance = MOCK_VARIANCES["VAR_002"]  # Legal, +566.7%

    verdict = verify_narrative_claim(
        "Legal costs were flat quarter over quarter.", variance, analytics,
    )

    assert verdict.verdict == "contradicted"


def test_reasoning_always_present_and_non_empty(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    analytics = MockAnalyticsEngine()
    for variance in MOCK_VARIANCES.values():
        verdict = verify_narrative_claim("Something changed.", variance, analytics)
        assert verdict.reasoning
        assert isinstance(verdict.reasoning, str)
