"""Optional follow-up Q&A over an already-generated explanation.

Deliberately last-priority (README section 10/24): only answers questions
about data already surfaced in the Explanation/Variance/Driver objects it's
given -- it does not re-query analytics or invent new figures.
"""

from __future__ import annotations

import os
from typing import Optional

from backend.contracts.schemas import Driver, Explanation, Variance


def answer_followup(
    question: str,
    variance: Variance,
    drivers: list[Driver],
    explanation: Explanation,
) -> str:
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            import anthropic

            driver_lines = "\n".join(
                f"- {d.entity} ({d.dimension}): {d.change:+,.0f}" for d in drivers
            )
            prompt = f"""Answer the follow-up question using ONLY the data below.
Do not invent or recompute any numbers.

Account: {variance.account}
Change: {variance.change:+,.0f} ({variance.change_pct:+.1f}%)
Drivers:
{driver_lines}
Explanation already given: {explanation.explanation}

Question: {question}

Answer in 1-2 sentences.
"""
            client = anthropic.Anthropic()
            resp = client.messages.create(
                model="claude-sonnet-5",
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.content[0].text.strip()
        except Exception:
            pass

    # Deterministic fallback: surface what we already know.
    if drivers:
        top = ", ".join(f"{d.entity} ({d.change:+,.0f})" for d in drivers)
        return f"Top contributors to this change were: {top}."
    return explanation.explanation
