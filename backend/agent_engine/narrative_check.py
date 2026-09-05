"""Optional feature: fact-check a public statement (earnings call quote,
press release line, investor letter) against the real driver/transaction
data for an account.

This is intentionally separate from `investigate_variance()` -- it is an
add-on the caller opts into explicitly (e.g. a "Check against transcript"
button in the UI), and nothing in the core workflow depends on it. If this
module were deleted, `investigate_variance()` / memory / explain would be
unaffected.

Design goal: make the "how" of the verdict fully explicit, not a black-box
LLM opinion. Entity matching against the claim text is done with plain
substring matching against the real driver entities Role 1 returned -- the
same guardrail as the rest of the agent: verification math comes from real
data, never from the LLM's own judgment of "does this sound true."

The optional LLM step (when ANTHROPIC_API_KEY is set) only writes the
human-readable `reasoning` sentence; the `verdict` and `match_pct` fields
are always computed deterministically first and handed to the LLM as facts
it must not contradict.
"""

from __future__ import annotations

import os
import re
import time
from typing import Optional

from backend.contracts.schemas import Driver, NarrativeVerdict, Variance
from backend.agent_engine.analytics_interface import AnalyticsEngine
from backend.agent_engine.drivers import select_important_drivers
from backend.observability.prismtrace_client import record_llm_call

# Share of the actual change that claimed/matched entities must cover to
# earn each verdict tier. Thresholds are deliberately explicit constants so
# the "how" of the check is inspectable, not tuned inside a prompt.
SUPPORTED_THRESHOLD = 0.5
PARTIAL_THRESHOLD = 0.15

_INCREASE_WORDS = {
    "increase", "increased", "grew", "growth", "up", "rose", "gain",
    "expansion", "higher", "surge", "spike", "jumped",
}
_DECREASE_WORDS = {
    "decrease", "decreased", "declined", "decline", "down", "fell",
    "drop", "dropped", "lower", "reduced", "reduction", "contraction",
}
_FLAT_WORDS = {
    "flat", "unchanged", "steady", "stable", "consistent", "level",
}

# A "flat" claim is only contradicted if the actual move is big enough to
# not plausibly be called "flat" -- avoids flagging genuinely small moves.
FLAT_CONTRADICTION_THRESHOLD_PCT = 5.0

# Phrases claiming growth/decline is diffuse rather than concentrated in
# one entity -- exactly the "concentration risk" question: a claim like
# this is checkable even with no named entity, by asking whether the
# single largest driver actually dominates the change.
_BROAD_BASED_PHRASES = [
    "broad-based", "broad based", "broadly based", "across the customer base",
    "across our customer base", "widespread", "diversified growth",
    "many customers", "across the board",
]
# If the single largest driver covers more than this share of the total
# change, the movement is concentrated, not broad-based.
CONCENTRATION_CONTRADICTION_THRESHOLD = 0.5


def _extract_claimed_entities(claim_text: str, known_entities: list[str]) -> list[str]:
    """Deterministic substring match of known driver entities inside the
    claim text (case-insensitive). No LLM involved -- this is the part
    that decides *what the claim is about*, so it must be inspectable."""
    text_lower = claim_text.lower()
    return [e for e in known_entities if e.lower() in text_lower]


def _claimed_direction(claim_text: str) -> Optional[str]:
    words = set(re.findall(r"[a-z]+", claim_text.lower()))
    if words & _FLAT_WORDS:
        return "flat"
    if words & _INCREASE_WORDS:
        return "increase"
    if words & _DECREASE_WORDS:
        return "decrease"
    return None


def _claims_broad_based(claim_text: str) -> bool:
    text_lower = claim_text.lower()
    return any(phrase in text_lower for phrase in _BROAD_BASED_PHRASES)


def _actual_direction(variance: Variance) -> str:
    return "increase" if variance.change >= 0 else "decrease"


def _direction_contradicts(claimed_dir: Optional[str], variance: Variance) -> bool:
    if claimed_dir is None:
        return False
    if claimed_dir == "flat":
        return abs(variance.change_pct) > FLAT_CONTRADICTION_THRESHOLD_PCT
    return claimed_dir != _actual_direction(variance)


def _llm_reasoning(
    claim_text: str,
    variance: Variance,
    verdict: str,
    match_pct: Optional[float],
    matched_entities: list[str],
    actual_drivers: list[Driver],
) -> Optional[str]:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic
    except ImportError:
        return None

    driver_lines = "\n".join(
        f"- {d.entity}: {d.change:+,.0f}" for d in actual_drivers
    )
    prompt = f"""You are fact-checking a public statement against real financial data.
The verdict and match percentage below are ALREADY COMPUTED from real data --
do not change them, recompute them, or contradict them. Only explain them in
1-2 plain sentences.

Statement: "{claim_text}"
Account: {variance.account}
Actual change: {variance.change:+,.0f} ({variance.change_pct:+.1f}%)
Actual top drivers:
{driver_lines or "(none)"}
Entities from the statement that were found in the real driver data: {matched_entities or "none"}
Computed verdict: {verdict}
Computed match percentage of the claim's mentioned entities vs. the actual change: {match_pct if match_pct is not None else "n/a"}

Explain, in 1-2 sentences, why the statement earns this verdict.
"""
    model = "claude-sonnet-5"
    messages = [{"role": "user", "content": prompt}]
    started = time.perf_counter()
    try:
        client = anthropic.Anthropic()
        resp = client.messages.create(model=model, max_tokens=200, messages=messages)
        text = resp.content[0].text.strip()
        record_llm_call(
            model=model, input_messages=messages, output_message=text,
            latency_ms=(time.perf_counter() - started) * 1000,
            agent_name="whyledger-narrative-check", session_id=variance.variance_id,
            token_count_input=getattr(resp.usage, "input_tokens", None),
            token_count_output=getattr(resp.usage, "output_tokens", None),
            metadata={"account": variance.account, "verdict": verdict},
        )
        return text
    except Exception as exc:
        record_llm_call(
            model=model, input_messages=messages, output_message="",
            latency_ms=(time.perf_counter() - started) * 1000,
            agent_name="whyledger-narrative-check", session_id=variance.variance_id,
            metadata={"account": variance.account, "verdict": verdict}, error=str(exc),
        )
        return None


def _template_reasoning(
    claim_text: str,
    variance: Variance,
    verdict: str,
    match_pct: Optional[float],
    matched_entities: list[str],
    actual_top_entities: list[str],
) -> str:
    if verdict == "contradicted":
        return (
            f'The statement implies the opposite direction of what the data shows: '
            f"{variance.account} actually {_actual_direction(variance)}d by "
            f"{abs(variance.change_pct):.1f}%."
        )
    if verdict == "unverifiable":
        return (
            "The statement does not name any specific entity that appears in the "
            f"real driver breakdown for {variance.account}, so it can't be checked "
            "against transaction-level data."
        )
    pct_txt = f"{match_pct * 100:.0f}%" if match_pct is not None else "an unclear share"
    if verdict == "supported":
        return (
            f"{', '.join(matched_entities)} {'is' if len(matched_entities) == 1 else 'are'} "
            f"named in the statement and actually account for {pct_txt} of the "
            f"{abs(variance.change_pct):.1f}% change -- consistent with the claim."
        )
    if verdict == "partially_supported":
        return (
            f"{', '.join(matched_entities)} {'is' if len(matched_entities) == 1 else 'are'} "
            f"named in the statement but only account for {pct_txt} of the actual change. "
            f"The remainder came from: {', '.join(e for e in actual_top_entities if e not in matched_entities) or 'other, unnamed drivers'}."
        )
    # unsupported
    return (
        f"{', '.join(matched_entities) or 'The entities named in the statement'} "
        f"account for only {pct_txt} of the actual change. The real top drivers were: "
        f"{', '.join(actual_top_entities) or 'not available'}."
    )


def verify_narrative_claim(
    claim_text: str,
    variance: Variance,
    analytics: AnalyticsEngine,
) -> NarrativeVerdict:
    """Check a public statement about `variance.account` against Role 1's
    real driver/transaction data. Fully explicit: every field needed to
    show the "how" of the verdict is on the returned object."""

    drivers = analytics.breakdown_variance(variance.variance_id)
    named_drivers, _ = select_important_drivers(variance, drivers)
    all_entities = [d.entity for d in drivers]
    actual_top_entities = [d.entity for d in named_drivers]

    claimed_entities = _extract_claimed_entities(claim_text, all_entities)
    claimed_dir = _claimed_direction(claim_text)
    claims_broad_based = _claims_broad_based(claim_text)

    matched_drivers = [d for d in drivers if d.entity in claimed_entities]
    total_abs = abs(variance.change) or sum(abs(d.change) for d in drivers) or 1.0
    match_pct = (
        sum(abs(d.change) for d in matched_drivers) / total_abs
        if claimed_entities
        else None
    )

    largest_driver = max(drivers, key=lambda d: abs(d.change)) if drivers else None
    largest_share = (abs(largest_driver.change) / total_abs) if largest_driver else 0.0
    # entities actually behind the verdict, for evidence/reasoning -- kept
    # separate from claimed_entities (what the claim literally named) so a
    # broad-based claim naming nobody doesn't get misrepresented as having
    # named the entity that disproves it.
    discovered_entities: list[str] = []

    if _direction_contradicts(claimed_dir, variance):
        verdict = "contradicted"
    elif claims_broad_based and not claimed_entities:
        if largest_driver is not None and largest_share > CONCENTRATION_CONTRADICTION_THRESHOLD:
            verdict = "contradicted"
            discovered_entities = [largest_driver.entity]
            match_pct = largest_share
        else:
            verdict = "supported"
            match_pct = 1.0 - largest_share
    elif not claimed_entities:
        verdict = "unverifiable"
    elif match_pct >= SUPPORTED_THRESHOLD:
        verdict = "supported"
    elif match_pct >= PARTIAL_THRESHOLD:
        verdict = "partially_supported"
    else:
        verdict = "unsupported"

    evidence_entities = discovered_entities or claimed_entities

    if claims_broad_based and not claimed_entities:
        if verdict == "contradicted":
            reasoning = (
                f"The claim describes broad-based movement, but {largest_driver.entity} alone "
                f"accounts for {largest_share * 100:.0f}% of the change -- this is concentrated "
                f"in a single entity, not broad-based."
            )
        else:
            reasoning = (
                f"No single entity dominates: the largest driver accounts for only "
                f"{largest_share * 100:.0f}% of the change, consistent with a broad-based movement."
            )
    else:
        reasoning = _llm_reasoning(
            claim_text, variance, verdict, match_pct, claimed_entities, named_drivers
        ) or _template_reasoning(
            claim_text, variance, verdict, match_pct, claimed_entities, actual_top_entities
        )

    evidence_drivers = [d for d in drivers if d.entity in evidence_entities] or matched_drivers or named_drivers
    transaction_ids: list[str] = []
    for d in evidence_drivers:
        txns = analytics.get_top_transactions(variance.variance_id, entity=d.entity)
        transaction_ids.extend(t.transaction_id for t in txns)

    return NarrativeVerdict(
        variance_id=variance.variance_id,
        claim_text=claim_text,
        claimed_entities=claimed_entities,
        matched_entities=evidence_entities,
        actual_top_entities=actual_top_entities,
        match_pct=match_pct,
        verdict=verdict,
        reasoning=reasoning,
        driver_ids=[d.driver_id for d in evidence_drivers],
        transaction_ids=transaction_ids,
    )
