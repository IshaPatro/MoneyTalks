"""Risk Graph Engine: models the subscription dataset as a directed,
weighted risk graph and extracts graph-theory risk metrics.

Optional feature, additive to the rest of the backend -- it reads the same
CSV schema `finance_engine` does (data/subscription_accounts.csv, matching
whyledger_frontend_reference_full.csv) but answers a different question
than Variance/Driver/Explanation do. Where `finance_engine` answers "what
changed and by how much," this answers "which accounts sit downstream of
the most systemic operational risk, and through which causal path." If
this module were deleted, nothing else in the backend would break.

--------------------------------------------------------------------------
Graph model: G = (V, E, W)
--------------------------------------------------------------------------
Nodes (V):
  - Account nodes: one per `account_id`, attributes {company_size,
    industry, current_mrr} (current_mrr = latest value seen in range).
  - Operational Risk Source nodes (fixed, shared across all accounts):
    Reliability_Risk, Support_Friction, Payment_Delay_Risk.
  - Financial Consequence nodes (fixed): SLA_Credit_Loss, Refund_Loss,
    Contraction_MRR, Churn_Risk.

Edges (E) and weights (W) -- all weights are non-negative dollar amounts
(or a dollar-denominated proxy), aggregated (summed) over every row in the
analysis window that satisfies the edge's condition:
  - Reliability_Risk -> SLA_Credit_Loss: sum(|sla_credit_amount|) over rows
    flagged `error_rate_driver_flag`.
  - Reliability_Risk -> Contraction_MRR: sum(|contraction_amount|) over
    rows flagged `error_rate_driver_flag`.
  - Support_Friction -> Refund_Loss: sum(|refund_amount|) over rows
    flagged `ticket_growth_driver_flag`.
  - Support_Friction -> Contraction_MRR: sum(|contraction_amount|) over
    rows flagged `ticket_growth_driver_flag`.
  - Payment_Delay_Risk -> Churn_Risk: for every row with
    `payment_delay_flag == 1`, weight = |churn_amount| if the account
    churned that same row, else `current_mrr` (the MRR put at risk).
  - Financial Consequence -> account_id: for every row with a nonzero
    category amount, weight = |amount| / mrr_base, where mrr_base is
    whichever of current_mrr/previous_mrr is nonzero (the "financial
    impact ratio to total MRR" the spec calls for).

This attribution (which operational signal "causes" which financial
category) is a modeling assumption, not a fact mined from the data --
it's documented here so it's inspectable and adjustable, the same
transparency principle used elsewhere in this backend (see
agent_engine/narrative_check.py's deterministic entity matching).

--------------------------------------------------------------------------
Metrics
--------------------------------------------------------------------------
1. Systemic Risk Score (PageRank) -- `nx.pagerank(G, weight="weight")`,
   read off each account node as its "Cascade Risk Index": how much of
   the graph's total risk mass eventually flows into this account.
2. Risk Amplifier Score -- weighted out-degree of the 3 operational risk
   source nodes, ranking which one drives the most downstream financial
   damage in aggregate.
3. Account Vulnerability -- weighted in-degree centrality per account
   node, plus the actual shortest paths (fewest hops) from each
   operational risk source to that account, via `nx.all_shortest_paths`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import networkx as nx
import pandas as pd

# ---- fixed node names -----------------------------------------------------
RELIABILITY_RISK = "Reliability_Risk"
SUPPORT_FRICTION = "Support_Friction"
PAYMENT_DELAY_RISK = "Payment_Delay_Risk"
OPERATIONAL_RISK_SOURCES = [RELIABILITY_RISK, SUPPORT_FRICTION, PAYMENT_DELAY_RISK]

SLA_CREDIT_LOSS = "SLA_Credit_Loss"
REFUND_LOSS = "Refund_Loss"
CONTRACTION_MRR = "Contraction_MRR"
CHURN_RISK = "Churn_Risk"
FINANCIAL_CONSEQUENCES = [SLA_CREDIT_LOSS, REFUND_LOSS, CONTRACTION_MRR, CHURN_RISK]

REQUIRED_COLUMNS = [
    "account_id", "month", "company_size", "industry", "current_mrr", "previous_mrr",
    "sla_credit_amount", "refund_amount", "contraction_amount", "churn_amount",
    "payment_delay_flag", "error_rate_driver_flag", "ticket_growth_driver_flag",
]


def load_risk_dataframe(csv_path: str | Path) -> pd.DataFrame:
    """Read just the columns the risk graph needs from the subscription
    CSV. Independent of `finance_engine.ingestion` on purpose -- this
    module doesn't need the transaction-list columns, so it stays a thin,
    self-contained reader."""
    df = pd.read_csv(csv_path, usecols=REQUIRED_COLUMNS)
    for flag_col in ("payment_delay_flag", "error_rate_driver_flag", "ticket_growth_driver_flag"):
        df[flag_col] = df[flag_col].fillna(False).astype(bool)
    return df


def _mrr_base(row: pd.Series) -> float:
    """Denominator for a "financial impact ratio to total MRR" -- use
    whichever of current/previous MRR is nonzero (current_mrr is 0 in the
    exact row an account fully churns)."""
    return row["current_mrr"] if row["current_mrr"] else (row["previous_mrr"] or 0.0)


def build_risk_graph(df: pd.DataFrame) -> nx.DiGraph:
    """Construct the directed, weighted risk graph from a (possibly
    period-filtered) slice of the subscription dataframe. Parallel
    contributions to the same edge are summed, per the module docstring's
    aggregation rule.
    """
    G = nx.DiGraph()

    for node in OPERATIONAL_RISK_SOURCES + FINANCIAL_CONSEQUENCES:
        G.add_node(node, kind="risk_source" if node in OPERATIONAL_RISK_SOURCES else "financial_consequence")

    account_attrs: dict[str, dict] = {}
    for _, row in df.iterrows():
        account_id = row["account_id"]
        # last value seen wins -- fine for either a single-period slice or
        # a multi-period aggregate (attributes are near-static per account).
        account_attrs[account_id] = {
            "kind": "account",
            "company_size": row["company_size"],
            "industry": row["industry"],
            "current_mrr": float(row["current_mrr"]),
        }

    for account_id, attrs in account_attrs.items():
        G.add_node(account_id, **attrs)

    def add_weight(u: str, v: str, amount: float) -> None:
        if amount <= 0:
            return
        if G.has_edge(u, v):
            G[u][v]["weight"] += amount
        else:
            G.add_edge(u, v, weight=amount)

    for _, row in df.iterrows():
        account_id = row["account_id"]
        sla = abs(row["sla_credit_amount"])
        refund = abs(row["refund_amount"])
        contraction = abs(row["contraction_amount"])
        churn = abs(row["churn_amount"])
        mrr_base = _mrr_base(row) or 1.0

        if row["error_rate_driver_flag"]:
            add_weight(RELIABILITY_RISK, SLA_CREDIT_LOSS, sla)
            add_weight(RELIABILITY_RISK, CONTRACTION_MRR, contraction)
        if row["ticket_growth_driver_flag"]:
            add_weight(SUPPORT_FRICTION, REFUND_LOSS, refund)
            add_weight(SUPPORT_FRICTION, CONTRACTION_MRR, contraction)
        if row["payment_delay_flag"]:
            at_risk = churn if churn > 0 else float(row["current_mrr"] or 0.0)
            add_weight(PAYMENT_DELAY_RISK, CHURN_RISK, at_risk)

        if sla:
            add_weight(SLA_CREDIT_LOSS, account_id, sla / mrr_base)
        if refund:
            add_weight(REFUND_LOSS, account_id, refund / mrr_base)
        if contraction:
            add_weight(CONTRACTION_MRR, account_id, contraction / mrr_base)
        if churn:
            add_weight(CHURN_RISK, account_id, churn / mrr_base)

    return G


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def compute_cascade_risk_index(G: nx.DiGraph) -> dict[str, float]:
    """PageRank across the whole graph, restricted to account nodes --
    the "Cascade Risk Index": how much systemic risk mass eventually
    reaches this account, not just its own direct incidents."""
    if G.number_of_edges() == 0:
        return {n: 0.0 for n, d in G.nodes(data=True) if d.get("kind") == "account"}
    scores = nx.pagerank(G, weight="weight")
    return {n: scores[n] for n, d in G.nodes(data=True) if d.get("kind") == "account"}


def compute_risk_amplifier_ranking(G: nx.DiGraph) -> list[tuple[str, float]]:
    """Weighted out-degree of each operational risk source -- ranks which
    one (Reliability_Risk / Support_Friction / Payment_Delay_Risk) drives
    the most downstream financial damage in aggregate. Returned sorted
    descending, so index 0 is the top amplifier."""
    ranking = [
        (source, float(G.out_degree(source, weight="weight")) if source in G else 0.0)
        for source in OPERATIONAL_RISK_SOURCES
    ]
    return sorted(ranking, key=lambda kv: kv[1], reverse=True)


def compute_account_vulnerability(G: nx.DiGraph) -> dict[str, float]:
    """Weighted in-degree centrality per account node: how much financial
    risk (as a fraction of MRR) flows into this account from all
    consequence nodes combined."""
    accounts = [n for n, d in G.nodes(data=True) if d.get("kind") == "account"]
    return {a: float(G.in_degree(a, weight="weight")) for a in accounts}


def find_cascading_loss_paths(G: nx.DiGraph, account_id: str) -> list[dict]:
    """Shortest (fewest-hop) risk paths from every operational risk source
    that can reach `account_id`, via `nx.all_shortest_paths`. Each result
    includes the path's nodes, its edges with weights, and the total
    weighted cost -- so a path is both structurally and financially
    explainable, not just a list of node names.
    """
    paths: list[dict] = []
    if account_id not in G:
        return paths

    for source in OPERATIONAL_RISK_SOURCES:
        if source not in G or not nx.has_path(G, source, account_id):
            continue
        for path in nx.all_shortest_paths(G, source, account_id):
            edges = [
                {"from": u, "to": v, "weight": G[u][v]["weight"]}
                for u, v in zip(path, path[1:])
            ]
            paths.append({
                "source": source,
                "path": path,
                "edges": edges,
                "total_weight": sum(e["weight"] for e in edges),
            })
    return paths


def _primary_risk_driver(G: nx.DiGraph, account_id: str, cascading_paths: list[dict]) -> Optional[str]:
    """The operational risk source contributing the most weighted risk
    mass to this specific account, traced through whichever cascading
    path carries the highest total weight. Falls back to the global
    top risk amplifier if this account has no traceable path (e.g. an
    account with no operational-risk-linked incidents at all)."""
    if cascading_paths:
        return max(cascading_paths, key=lambda p: p["total_weight"])["source"]
    ranking = compute_risk_amplifier_ranking(G)
    return ranking[0][0] if ranking and ranking[0][1] > 0 else None


@dataclass
class RiskGraphResult:
    accounts: pd.DataFrame
    risk_amplifier_ranking: list[tuple[str, float]]
    json_graph_data: dict

    def to_dict(self) -> dict:
        return {
            "accounts": self.accounts.to_dict(orient="records"),
            "risk_amplifier_ranking": self.risk_amplifier_ranking,
            "json_graph_data": self.json_graph_data,
        }


def analyze_account_risk(
    csv_path: str | Path,
    period: Optional[str] = None,
    month_to_period=None,
) -> RiskGraphResult:
    """Main runner: build the risk graph for `csv_path` (optionally
    filtered to one calendar `period`, e.g. "2026-08" -- requires
    `month_to_period` from `backend.finance_engine.ingestion` to map the
    raw integer `month` column onto period labels; without it, or if
    `period` is None, every row in the file is aggregated into one static
    graph) and compute every metric in this module.

    Returns a RiskGraphResult with:
      - accounts: DataFrame[account_id, graph_pagerank_risk_score,
        account_vulnerability_score, primary_risk_driver_node,
        cascading_loss_paths]
      - risk_amplifier_ranking: [(node, weighted_out_degree), ...] desc
      - json_graph_data: nx.node_link_data(G), for frontend visualization
    """
    df = load_risk_dataframe(csv_path)

    if period is not None:
        if month_to_period is None:
            raise ValueError("month_to_period(month:int)->str is required when filtering by period")
        df = df[df["month"].apply(month_to_period) == period]

    G = build_risk_graph(df)

    pagerank_scores = compute_cascade_risk_index(G)
    vulnerability_scores = compute_account_vulnerability(G)
    amplifier_ranking = compute_risk_amplifier_ranking(G)

    rows = []
    for account_id in sorted(pagerank_scores):
        cascading_paths = find_cascading_loss_paths(G, account_id)
        rows.append({
            "account_id": account_id,
            "graph_pagerank_risk_score": pagerank_scores[account_id],
            "account_vulnerability_score": vulnerability_scores.get(account_id, 0.0),
            "primary_risk_driver_node": _primary_risk_driver(G, account_id, cascading_paths),
            "cascading_loss_paths": cascading_paths,
        })

    accounts_df = pd.DataFrame(rows).sort_values(
        "graph_pagerank_risk_score", ascending=False
    ).reset_index(drop=True)

    return RiskGraphResult(
        accounts=accounts_df,
        risk_amplifier_ranking=amplifier_ranking,
        json_graph_data=nx.node_link_data(G, edges="links"),
    )
