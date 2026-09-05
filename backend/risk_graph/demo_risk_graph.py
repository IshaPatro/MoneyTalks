"""Demo for the optional Risk Graph feature, against the real dataset.

Run directly:

    python3 -m backend.risk_graph.demo_risk_graph

Shows the systemic-risk view on top of the same data
`finance_engine.demo_pipeline` already investigates account-by-account:
which accounts are downstream of the most operational risk, which
operational risk source (Reliability_Risk / Support_Friction /
Payment_Delay_Risk) is doing the most aggregate financial damage, and the
exact causal path from incident to dollar loss for the top account.
"""

from __future__ import annotations

from pathlib import Path

from backend.risk_graph.risk_graph_engine import analyze_account_risk

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_CSV = REPO_ROOT / "data" / "subscription_accounts.csv"


def _line(char: str = "-", n: int = 72) -> None:
    print(char * n)


def main() -> None:
    result = analyze_account_risk(DATA_CSV)

    print("1. RISK AMPLIFIER RANKING (which operational risk source does the most damage)")
    _line()
    for node, weighted_out_degree in result.risk_amplifier_ranking:
        print(f"  {node:<20} {weighted_out_degree:>14,.2f} total weighted downstream impact")
    print()

    print("2. TOP 10 ACCOUNTS BY CASCADE RISK INDEX (PageRank)")
    _line()
    top10 = result.accounts.head(10)
    for _, row in top10.iterrows():
        print(f"  {row['account_id']:<10} score={row['graph_pagerank_risk_score']:.4f}  "
              f"driver={row['primary_risk_driver_node']}")
    print()

    top_account = top10.iloc[0]
    print(f"3. CASCADING LOSS PATH FOR THE #1 RISK ACCOUNT: {top_account['account_id']}")
    _line()
    for path in top_account["cascading_loss_paths"]:
        chain = " -> ".join(path["path"])
        print(f"  {chain}   (weight {path['total_weight']:.2f})")
        for edge in path["edges"]:
            print(f"      {edge['from']} -> {edge['to']}: {edge['weight']:.2f}")
    print()

    print("4. GRAPH SIZE (for frontend visualization via json_graph_data)")
    _line()
    print(f"  {len(result.json_graph_data['nodes'])} nodes, {len(result.json_graph_data['links'])} links")


if __name__ == "__main__":
    main()
