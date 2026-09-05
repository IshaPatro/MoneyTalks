from .investigate import investigate_variance
from .drivers import select_important_drivers
from .explain import generate_explanation
from .followup import answer_followup
from .narrative_check import verify_narrative_claim

__all__ = [
    "investigate_variance",
    "select_important_drivers",
    "generate_explanation",
    "answer_followup",
    "verify_narrative_claim",  # optional: narrative fact-check feature
]
