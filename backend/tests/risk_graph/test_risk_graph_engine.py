"""Tests for the risk graph engine: a small hand-verifiable synthetic
graph, plus validation against the real dataset's seeded SLA-credit-shock
account (ACC-0002), which should surface as a clear, traceable risk case.
"""

from pathlib import Path

import networkx as nx
import pandas as pd
import pytest

from backend.risk_graph.risk_graph_engine import (
    CHURN_RISK, CONTRACTION_MRR, PAYMENT_DELAY_RISK, REFUND_LOSS,
    RELIABILITY_RISK, SLA_CREDIT_LOSS, SUPPORT_FRICTION,
    analyze_account_risk, build_risk_graph, compute_account_vulnerability,
    compute_cascade_risk_index, compute_risk_amplifier_ranking,
    find_cascading_loss_paths, load_risk_dataframe,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_CSV = REPO_ROOT / "data" / "subscription_accounts.csv"


def _toy_df() -> pd.DataFrame:
    """Two accounts, hand-designed so every edge type is exercised and
    the expected winner of each metric is known in advance."""
    return pd.DataFrame([
        # ACC-A: a reliability incident causes a large SLA credit.
        {
            "account_id": "ACC-A", "month": 1, "company_size": "Enterprise",
            "industry": "Technology", "current_mrr": 100_000.0, "previous_mrr": 108_000.0,
            "sla_credit_amount": -8_000.0, "refund_amount": 0.0, "contraction_amount": 0.0,
            "churn_amount": 0.0, "payment_delay_flag": False,
            "error_rate_driver_flag": True, "ticket_growth_driver_flag": False,
        },
        # ACC-B: a payment delay precedes churn (the conditional edge).
        {
            "account_id": "ACC-B", "month": 1, "company_size": "SMB",
            "industry": "Retail", "current_mrr": 0.0, "previous_mrr": 5_000.0,
            "sla_credit_amount": 0.0, "refund_amount": -500.0, "contraction_amount": 0.0,
            "churn_amount": -5_000.0, "payment_delay_flag": True,
            "error_rate_driver_flag": False, "ticket_growth_driver_flag": True,
        },
    ])


def test_build_risk_graph_creates_expected_nodes_and_edges():
    G = build_risk_graph(_toy_df())

    assert G.nodes["ACC-A"]["kind"] == "account"
    assert G.nodes["ACC-A"]["industry"] == "Technology"

    assert G.has_edge(RELIABILITY_RISK, SLA_CREDIT_LOSS)
    assert G[RELIABILITY_RISK][SLA_CREDIT_LOSS]["weight"] == pytest.approx(8_000.0)
    assert G.has_edge(SLA_CREDIT_LOSS, "ACC-A")

    assert G.has_edge(SUPPORT_FRICTION, REFUND_LOSS)
    assert G.has_edge(PAYMENT_DELAY_RISK, CHURN_RISK)
    assert G.has_edge(CHURN_RISK, "ACC-B")


def test_edges_with_no_amount_are_not_created():
    G = build_risk_graph(_toy_df())
    # ACC-A had no contraction/refund/churn amounts -- no edges from those
    # consequence nodes into it.
    assert not G.has_edge(CONTRACTION_MRR, "ACC-A")
    assert not G.has_edge(REFUND_LOSS, "ACC-A")
    assert not G.has_edge(CHURN_RISK, "ACC-A")


def test_pagerank_returns_only_account_nodes():
    G = build_risk_graph(_toy_df())
    scores = compute_cascade_risk_index(G)
    assert set(scores.keys()) == {"ACC-A", "ACC-B"}
    assert all(0 <= s <= 1 for s in scores.values())


def test_risk_amplifier_ranking_sorted_descending():
    G = build_risk_graph(_toy_df())
    ranking = compute_risk_amplifier_ranking(G)
    values = [v for _, v in ranking]
    assert values == sorted(values, reverse=True)
    assert {n for n, _ in ranking} == {RELIABILITY_RISK, SUPPORT_FRICTION, PAYMENT_DELAY_RISK}


def test_account_vulnerability_reflects_incoming_risk():
    G = build_risk_graph(_toy_df())
    vulnerability = compute_account_vulnerability(G)
    # ACC-B has both a refund and a churn edge feeding it -- strictly more
    # incoming weighted risk than ACC-A, which only has the SLA credit.
    assert vulnerability["ACC-B"] > 0
    assert vulnerability["ACC-A"] > 0


def test_cascading_loss_paths_trace_reliability_to_account():
    G = build_risk_graph(_toy_df())
    paths = find_cascading_loss_paths(G, "ACC-A")
    assert paths
    reliability_path = next(p for p in paths if p["source"] == RELIABILITY_RISK)
    assert reliability_path["path"] == [RELIABILITY_RISK, SLA_CREDIT_LOSS, "ACC-A"]
    assert reliability_path["total_weight"] > 0


def test_cascading_loss_paths_empty_for_unknown_account():
    G = build_risk_graph(_toy_df())
    assert find_cascading_loss_paths(G, "ACC-DOES-NOT-EXIST") == []


def test_no_edges_graph_returns_zero_pagerank():
    G = build_risk_graph(pd.DataFrame([{
        "account_id": "ACC-Z", "month": 1, "company_size": "SMB", "industry": "Retail",
        "current_mrr": 1000.0, "previous_mrr": 1000.0, "sla_credit_amount": 0.0,
        "refund_amount": 0.0, "contraction_amount": 0.0, "churn_amount": 0.0,
        "payment_delay_flag": False, "error_rate_driver_flag": False,
        "ticket_growth_driver_flag": False,
    }]))
    scores = compute_cascade_risk_index(G)
    assert scores == {"ACC-Z": 0.0}


# ---------------------------------------------------------------------
# Real dataset
# ---------------------------------------------------------------------

def test_load_risk_dataframe_from_real_csv():
    df = load_risk_dataframe(DATA_CSV)
    assert "ACC-0002" in set(df["account_id"])
    assert df["payment_delay_flag"].dtype == bool


def test_analyze_account_risk_end_to_end():
    result = analyze_account_risk(DATA_CSV)

    assert not result.accounts.empty
    assert list(result.accounts.columns) == [
        "account_id", "graph_pagerank_risk_score", "account_vulnerability_score",
        "primary_risk_driver_node", "cascading_loss_paths",
    ]
    # sorted descending by pagerank
    scores = result.accounts["graph_pagerank_risk_score"].tolist()
    assert scores == sorted(scores, reverse=True)

    assert "nodes" in result.json_graph_data and "links" in result.json_graph_data


def test_seeded_sla_shock_account_is_traceable_top_risk():
    """ACC-0002 has a large, deliberate SLA-credit shock correlated with a
    reliability incident (see generate_subscription_data.py) -- it should
    rank at or near the top of systemic risk, with a clean, traceable
    Reliability_Risk -> SLA_Credit_Loss -> ACC-0002 path."""
    result = analyze_account_risk(DATA_CSV)
    row = result.accounts[result.accounts["account_id"] == "ACC-0002"].iloc[0]

    assert row["primary_risk_driver_node"] == RELIABILITY_RISK
    paths = row["cascading_loss_paths"]
    reliability_paths = [p for p in paths if p["source"] == RELIABILITY_RISK]
    assert reliability_paths
    assert reliability_paths[0]["path"] == [RELIABILITY_RISK, SLA_CREDIT_LOSS, "ACC-0002"]

    # top-10 by pagerank -- a real, seeded incident should not be buried.
    top_10 = set(result.accounts.head(10)["account_id"])
    assert "ACC-0002" in top_10


def test_period_filtering(monkeypatch):
    from backend.finance_engine.ingestion import month_to_period

    result_all = analyze_account_risk(DATA_CSV)
    result_one_month = analyze_account_risk(DATA_CSV, period="2025-10", month_to_period=month_to_period)

    assert len(result_one_month.accounts) <= len(result_all.accounts)


def test_period_filtering_requires_month_to_period():
    with pytest.raises(ValueError):
        analyze_account_risk(DATA_CSV, period="2025-10")
