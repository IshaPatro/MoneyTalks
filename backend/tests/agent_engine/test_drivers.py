from backend.contracts.schemas import Driver, Variance
from backend.agent_engine.drivers import select_important_drivers


def make_variance(change=260000, change_pct=31.7):
    return Variance(
        variance_id="VAR_001", account="Enterprise Revenue",
        previous=820000, current=820000 + change, change=change, change_pct=change_pct,
    )


def test_selects_top_named_drivers_above_threshold():
    variance = make_variance()
    drivers = [
        Driver(driver_id="D1", dimension="customer", entity="Acme", change=53000),
        Driver(driver_id="D2", dimension="customer", entity="Globex", change=44000),
        Driver(driver_id="D3", dimension="customer", entity="Umbrella", change=33000),
        Driver(driver_id="D4", dimension="customer", entity="Other", change=130000),
    ]
    named, share = select_important_drivers(variance, drivers)
    # Other (130k) is largest but not a real named entity in this test;
    # ranking is purely by magnitude, so it will be included by MAX_NAMED_DRIVERS.
    assert len(named) <= 3
    assert named[0].entity == "Other"
    assert 0 < share <= 1.5  # sanity: share derived from real numbers, not invented


def test_uses_role1_numbers_not_recomputed():
    variance = make_variance(change=260000, change_pct=31.7)
    drivers = [
        Driver(driver_id="D1", dimension="customer", entity="Acme", change=53000),
        Driver(driver_id="D2", dimension="customer", entity="Globex", change=44000),
        Driver(driver_id="D3", dimension="customer", entity="Umbrella", change=33000),
    ]
    named, share = select_important_drivers(variance, drivers)
    total_named_change = sum(d.change for d in named)
    assert total_named_change == 53000 + 44000 + 33000
    assert share == total_named_change / variance.change


def test_no_drivers_returns_empty():
    variance = make_variance()
    named, share = select_important_drivers(variance, [])
    assert named == []
    assert share == 0.0


def test_small_drivers_still_named_if_nothing_bigger():
    variance = make_variance(change=1000, change_pct=1.0)
    drivers = [Driver(driver_id="D1", dimension="customer", entity="Tiny", change=10)]
    named, share = select_important_drivers(variance, drivers)
    assert len(named) == 1  # at least one driver always named
