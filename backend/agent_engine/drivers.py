"""Driver selection: decide which drivers matter enough to mention.

All numbers here (change, change_pct) are taken verbatim from Role 1's
Driver/Variance objects -- this module only ranks and groups them, it never
recomputes a dollar amount or percentage itself.
"""

from __future__ import annotations

from backend.contracts.schemas import Driver, Variance

# Drivers below this share of the total absolute movement get folded into
# an implicit "everything else" bucket rather than named individually.
MIN_SHARE_TO_NAME = 0.10
MAX_NAMED_DRIVERS = 3


def select_important_drivers(
    variance: Variance, drivers: list[Driver]
) -> tuple[list[Driver], float]:
    """Pick the drivers worth naming in the explanation.

    Returns (named_drivers, named_share) where named_share is the fraction
    of the total variance's absolute change that the named drivers
    collectively account for (computed from Role 1's own `change` values,
    e.g. 130k/260k -> 0.5 -- not independently derived).
    """
    if not drivers:
        return [], 0.0

    total_abs = abs(variance.change) or sum(abs(d.change) for d in drivers)
    ranked = sorted(drivers, key=lambda d: abs(d.change), reverse=True)

    named: list[Driver] = []
    for d in ranked[:MAX_NAMED_DRIVERS]:
        share = abs(d.change) / total_abs if total_abs else 0
        if share >= MIN_SHARE_TO_NAME or not named:
            named.append(d)

    named_change = sum(d.change for d in named)
    named_share = named_change / variance.change if variance.change else 0.0
    return named, named_share
