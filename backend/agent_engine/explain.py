"""Turn structured financial analysis into a concise natural-language
explanation.

The LLM (when available) only writes prose from numbers it's handed --
it never computes totals, changes, or percentages itself. Every figure in
the prompt comes from Role 1's Variance/Driver objects. If no LLM is
configured (no ANTHROPIC_API_KEY, e.g. in tests/CI), a deterministic
template produces an equivalent, if less fluent, explanation so the rest
of the pipeline still works end to end.
"""

from __future__ import annotations

import os
import time
from typing import Optional

from backend.contracts.schemas import Driver, Explanation, Variance
from backend.observability.prismtrace_client import record_llm_call


def _direction(change: float) -> str:
    return "increased" if change >= 0 else "decreased"


def _fmt_money(n: float) -> str:
    return f"${abs(n):,.0f}"


def _template_explanation(
    variance: Variance,
    named_drivers: list[Driver],
    named_share: float,
    historical_note: Optional[str],
) -> str:
    direction = _direction(variance.change)
    headline_sentence = (
        f"{variance.account} {direction} {_fmt_money(variance.change)}, "
        f"or {abs(variance.change_pct):.1f}%."
    )

    driver_sentence = ""
    if named_drivers:
        names = [d.entity for d in named_drivers]
        if len(names) == 1:
            who = names[0]
        elif len(names) == 2:
            who = f"{names[0]} and {names[1]}"
        else:
            who = f"{', '.join(names[:-1])} and {names[-1]}"
        verb = "was" if len(named_drivers) == 1 else "were"
        driver_sentence = (
            f" {who} {verb} the largest contributor"
            f"{'s' if len(named_drivers) > 1 else ''}, "
            f"accounting for approximately {abs(named_share) * 100:.0f}% "
            f"of the change."
        )

    context_sentence = f" {historical_note}" if historical_note else ""
    return (headline_sentence + driver_sentence + context_sentence).strip()


def _llm_explanation(
    variance: Variance,
    named_drivers: list[Driver],
    named_share: float,
    historical_note: Optional[str],
) -> Optional[str]:
    """Try to generate the narrative with Claude. Returns None if no API
    key is configured or the call fails, so callers can fall back."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic
    except ImportError:
        return None

    driver_lines = "\n".join(
        f"- {d.entity} ({d.dimension}): {d.change:+,.0f}" for d in named_drivers
    )
    prompt = f"""You are a financial analyst writing a concise, factual explanation
of a period-over-period change. You must ONLY use the numbers given below --
never invent, recompute, or adjust any figure.

Account: {variance.account}
Previous: {variance.previous:,.0f}
Current: {variance.current:,.0f}
Change: {variance.change:+,.0f} ({variance.change_pct:+.1f}%)

Top drivers (already ranked and computed, do not recompute):
{driver_lines or "(no driver breakdown available)"}

Named drivers collectively account for {named_share * 100:.0f}% of the change.

Historical context (may or may not be relevant, never let it override the
current numbers above): {historical_note or "none"}

Write 2-3 sentences: what changed, why (top drivers), and historical context
if relevant. Be concise and concrete. Do not restate the raw prompt.
"""
    model = "claude-sonnet-5"
    messages = [{"role": "user", "content": prompt}]
    started = time.perf_counter()
    try:
        client = anthropic.Anthropic()
        resp = client.messages.create(model=model, max_tokens=300, messages=messages)
        text = resp.content[0].text.strip()
        record_llm_call(
            model=model, input_messages=messages, output_message=text,
            latency_ms=(time.perf_counter() - started) * 1000,
            agent_name="whyledger-explain", session_id=variance.variance_id,
            token_count_input=getattr(resp.usage, "input_tokens", None),
            token_count_output=getattr(resp.usage, "output_tokens", None),
            metadata={"account": variance.account},
        )
        return text
    except Exception as exc:
        record_llm_call(
            model=model, input_messages=messages, output_message="",
            latency_ms=(time.perf_counter() - started) * 1000,
            agent_name="whyledger-explain", session_id=variance.variance_id,
            metadata={"account": variance.account}, error=str(exc),
        )
        return None


def generate_explanation(
    variance: Variance,
    named_drivers: list[Driver],
    named_share: float,
    transaction_ids: list[str],
    historical_note: Optional[str] = None,
) -> Explanation:
    text = _llm_explanation(variance, named_drivers, named_share, historical_note)
    if text is None:
        text = _template_explanation(variance, named_drivers, named_share, historical_note)

    direction = _direction(variance.change)
    headline = f"{variance.account} {direction} {abs(variance.change_pct):.1f}%"

    return Explanation(
        variance_id=variance.variance_id,
        headline=headline,
        explanation=text,
        driver_ids=[d.driver_id for d in named_drivers],
        transaction_ids=transaction_ids,
        historical_context=historical_note,
    )
