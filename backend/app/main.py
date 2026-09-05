"""Rough integration layer (Role 3 territory, stood up here just so the
backend is actually clickable/testable): a minimal FastAPI app serving
the endpoints from README section 14, backed by the real FinanceEngine +
agent_engine + memory + risk_graph, plus a single static HTML/JS page
(no build step) implementing the three screens from README section 15.

Run:

    source .venv/bin/activate
    uvicorn backend.app.main:app --reload

Then open http://127.0.0.1:8000/
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.finance_engine.engine import FinanceEngine, PORTFOLIO_ACCOUNT_NAME
from backend.integration.dashboard import build_dashboard
from backend.agent_engine.narrative_check import verify_narrative_claim
from backend.memory.store import MemoryStore
from backend.risk_graph.risk_graph_engine import analyze_account_risk

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_CSV = REPO_ROOT / "data" / "subscription_accounts.csv"
STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="WhyLedger API (rough demo build)")

_engine: Optional[FinanceEngine] = None
_memory: Optional[MemoryStore] = None
_runs: dict[str, dict] = {}


def _get_engine() -> FinanceEngine:
    global _engine
    if _engine is None:
        _engine = FinanceEngine.from_csv(DATA_CSV)
    return _engine


def _get_memory() -> MemoryStore:
    global _memory
    if _memory is None:
        _memory = MemoryStore(REPO_ROOT / "backend" / "memory" / "app.db")
    return _memory


# ---------------------------------------------------------------------
# request/response models
# ---------------------------------------------------------------------

class AnalysisRequest(BaseModel):
    current_period: str
    comparison_period: str
    top_n: int = 10


class FeedbackRequest(BaseModel):
    run_id: str
    variance_id: str
    confirmed: bool
    corrected_explanation: Optional[str] = None


class NarrativeCheckRequest(BaseModel):
    run_id: str
    variance_id: str
    claim: str


# ---------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------

@app.get("/api/periods")
def get_periods() -> dict:
    engine = _get_engine()
    return {"periods": engine.dataset.periods}


@app.post("/api/analysis")
def create_analysis(req: AnalysisRequest) -> dict:
    engine = _get_engine()
    memory = _get_memory()

    try:
        portfolio = engine.get_portfolio_variance(req.current_period, req.comparison_period)
        cards = build_dashboard(
            engine, req.current_period, req.comparison_period,
            memory=memory, top_n=req.top_n,
        )
    except Exception as exc:  # noqa: BLE001 -- surface a readable error to the UI
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    run_id = str(uuid.uuid4())
    _runs[run_id] = {
        "current_period": req.current_period,
        "comparison_period": req.comparison_period,
        "cards": {c.variance_id: c for c in cards},
        "portfolio": portfolio,
    }

    return {
        "run_id": run_id,
        "current_period": req.current_period,
        "comparison_period": req.comparison_period,
        "portfolio": {
            "account": portfolio.account, "previous": portfolio.previous,
            "current": portfolio.current, "change": portfolio.change,
            "change_pct": portfolio.change_pct,
        },
        "variances": [
            {
                "variance_id": c.variance_id, "rank": c.rank, "account": c.account,
                "change": c.change, "change_pct": c.change_pct, "direction": c.direction,
                "headline": c.headline, "is_material": c.is_material,
            }
            for c in cards
        ],
    }


@app.get("/api/analysis/{run_id}/variances/{variance_id}")
def get_variance(run_id: str, variance_id: str) -> dict:
    run = _runs.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Unknown run_id -- run /api/analysis again")
    card = run["cards"].get(variance_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Unknown variance_id for this run")
    return card.to_dict()


@app.post("/api/feedback")
def post_feedback(req: FeedbackRequest) -> dict:
    run = _runs.get(req.run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Unknown run_id")
    card = run["cards"].get(req.variance_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Unknown variance_id for this run")

    explanation_text = req.corrected_explanation if (not req.confirmed and req.corrected_explanation) else card.explanation
    memory = _get_memory()
    saved = memory.save_confirmed_context(
        account=card.account, period=run["current_period"],
        explanation=explanation_text, confirmed=True,
    )
    return {"status": "saved", "account": saved.account, "period": saved.period, "explanation": saved.explanation}


@app.post("/api/narrative-check")
def post_narrative_check(req: NarrativeCheckRequest) -> dict:
    run = _runs.get(req.run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Unknown run_id")
    engine = _get_engine()

    if req.variance_id == run["portfolio"].variance_id:
        variance = run["portfolio"]
    else:
        variances = engine.compare_periods(run["current_period"], run["comparison_period"])
        variance = next((v for v in variances if v.variance_id == req.variance_id), None)
        if variance is None:
            raise HTTPException(status_code=404, detail="Unknown variance_id for this run")

    verdict = verify_narrative_claim(req.claim, variance, engine)
    return verdict.model_dump()


@app.get("/api/risk-graph")
def get_risk_graph(top_n: int = 15) -> dict:
    result = analyze_account_risk(DATA_CSV)
    top = result.accounts.head(top_n)
    return {
        "risk_amplifier_ranking": result.risk_amplifier_ranking,
        "accounts": top.to_dict(orient="records"),
        "json_graph_data": result.json_graph_data,
    }


# ---------------------------------------------------------------------
# static frontend
# ---------------------------------------------------------------------

@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
