from backend.contracts.schemas import Driver, Variance
from backend.agent_engine.explain import generate_explanation


def test_template_explanation_no_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    variance = Variance(
        variance_id="VAR_001", account="Enterprise Revenue",
        previous=820000, current=1080000, change=260000, change_pct=31.7,
    )
    drivers = [
        Driver(driver_id="D1", dimension="customer", entity="Acme", change=53000),
        Driver(driver_id="D2", dimension="customer", entity="Globex", change=44000),
    ]
    result = generate_explanation(
        variance, drivers, named_share=0.37, transaction_ids=["TX1", "TX2"],
        historical_note="Similar growth seen last quarter.",
    )
    assert result.variance_id == "VAR_001"
    assert "Enterprise Revenue" in result.explanation
    assert "31.7" in result.explanation
    assert "Acme" in result.explanation and "Globex" in result.explanation
    assert result.driver_ids == ["D1", "D2"]
    assert result.transaction_ids == ["TX1", "TX2"]
    assert result.historical_context == "Similar growth seen last quarter."


def test_decrease_direction_language(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    variance = Variance(
        variance_id="VAR_009", account="Marketing",
        previous=100000, current=70000, change=-30000, change_pct=-30.0,
    )
    result = generate_explanation(variance, [], named_share=0.0, transaction_ids=[])
    assert "decreased" in result.explanation
    assert "decreased" in result.headline
