from __future__ import annotations

import base64
import html
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from backend.agent_engine.investigate import investigate_variance
from backend.agent_engine.narrative_check import verify_narrative_claim
from backend.finance_engine.engine import FinanceEngine
from backend.finance_engine.ingestion import month_to_period
from backend.memory.store import MemoryStore
from backend.risk_graph.risk_graph_engine import analyze_account_risk

import networkx as nx

# The real, generated dataset (see data/generate_subscription_data.py) --
# small enough to load directly, no external multi-GB file required.
DATA_PATH = ROOT / "data" / "subscription_accounts.csv"
LOGO_PATH = ROOT / "assets" / "logo.png"

BLACK = "#000000"
DARK_BLUE = "#184D87"
LIGHT_BLUE = "#33A1DD"
TEAL = "#3AC0EF"
WHITE = "#FFFFFF"
GREEN = "#35D07F"
RED = "#FF5C6C"

st.set_page_config(
    page_title="WhaleWatch | CFO Revenue Intelligence",
    page_icon=str(LOGO_PATH),
    layout="wide",
    initial_sidebar_state="collapsed",
)


@st.cache_data(show_spinner=False)
def load_real_data(path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load the real (small, ~1k row) generated dataset directly -- no
    external multi-GB file, no chunked streaming needed."""
    columns = [
        "account_id", "month", "company_size", "industry", "contract_type",
        "regime_state", "current_mrr", "previous_mrr", "mrr_change",
        "positive_transaction_amount", "negative_transaction_amount",
        "expansion_amount", "churn_amount", "churn_flag",
    ]
    df = pd.read_csv(path, usecols=columns)

    numeric = [
        "current_mrr", "previous_mrr", "mrr_change", "positive_transaction_amount",
        "negative_transaction_amount", "expansion_amount", "churn_amount",
    ]
    df[numeric] = df[numeric].fillna(0)
    df["churn_flag"] = df["churn_flag"].fillna(False).astype(int)
    df["active_customer"] = df["current_mrr"].gt(0).astype(int)

    monthly = df.groupby("month", as_index=False).agg(
        total_mrr=("current_mrr", "sum"), previous_mrr=("previous_mrr", "sum"),
        net_change=("mrr_change", "sum"), expansion=("positive_transaction_amount", "sum"),
        losses=("negative_transaction_amount", "sum"), churn_mrr=("churn_amount", "sum"),
        churned=("churn_flag", "sum"), active_customers=("active_customer", "sum"),
        largest_account_mrr=("current_mrr", "max"),
    )
    # Derive the calendar period straight from the integer month index --
    # avoids aggregating the raw (partly-empty) timestamp string column,
    # which is fragile and was the source of a real crash here.
    monthly["period"] = pd.to_datetime(monthly["month"].apply(month_to_period))
    monthly["month_label"] = monthly["period"].dt.strftime("%b %Y")
    monthly["underlying_mrr"] = monthly["total_mrr"] - monthly["largest_account_mrr"]
    monthly = monthly.sort_values("month").reset_index(drop=True)

    latest_month = int(df["month"].max())
    latest = df[df["month"].eq(latest_month)].drop_duplicates("account_id", keep="last").copy()
    latest["customer"] = latest["account_id"].astype(str)  # account_id is already "ACC-0001"-style
    latest["mrr"] = latest["current_mrr"].clip(lower=0)
    return monthly, latest


@st.cache_resource(show_spinner=False)
def load_engine() -> tuple[FinanceEngine, MemoryStore]:
    engine = FinanceEngine.from_csv(DATA_PATH)
    memory = MemoryStore(ROOT / "backend" / "memory" / "app.db")
    return engine, memory


def image_data_uri(path: Path) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def money(value: float, compact: bool = False, signed: bool = False) -> str:
    prefix = "+" if signed and value > 0 else ""
    if compact and abs(value) >= 1000:
        return f"{prefix}${value / 1000:,.1f}K"
    return f"{prefix}${value:,.0f}"


def percentage(value: float, signed: bool = False) -> str:
    prefix = "+" if signed and value > 0 else ""
    return f"{prefix}{value:.1%}"


def metric_card(
    label: str,
    value: str,
    detail: str,
    icon: str,
    state: str = "neutral",
) -> str:
    return f"""
    <div class="metric-card {state}">
      <div class="metric-head"><span>{html.escape(label)}</span><i>{icon}</i></div>
      <div class="metric-value">{html.escape(value)}</div>
      <div class="metric-detail">{detail}</div>
    </div>
    """


def chart_base() -> go.Figure:
    fig = go.Figure()
    fig.update_layout(
        autosize=True,
        height=275,
        margin=dict(l=12, r=14, t=30, b=28),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, Arial, sans-serif", color="rgba(255,255,255,.62)", size=10),
        hoverlabel=dict(bgcolor=BLACK, bordercolor=TEAL, font_color=WHITE),
        legend=dict(
            orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
            font=dict(color="rgba(255,255,255,.58)", size=9),
        ),
    )
    fig.update_xaxes(showgrid=False, zeroline=False, automargin=True, tickfont=dict(color="rgba(255,255,255,.46)"))
    fig.update_yaxes(
        gridcolor="rgba(255,255,255,.07)", zeroline=False, automargin=True,
        tickfont=dict(color="rgba(255,255,255,.46)"),
    )
    return fig


def revenue_quality_chart(monthly: pd.DataFrame) -> go.Figure:
    fig = chart_base()
    fig.add_trace(
        go.Scatter(
            x=monthly["period"], y=monthly["total_mrr"], name="Total MRR",
            mode="lines+markers", line=dict(color=LIGHT_BLUE, width=3, shape="spline"),
            marker=dict(size=6, color=WHITE, line=dict(color=LIGHT_BLUE, width=2)),
            fill="tozeroy", fillcolor="rgba(51,161,221,.12)",
            hovertemplate="<b>%{x|%b}</b><br>Total MRR $%{y:,.0f}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=monthly["period"], y=monthly["underlying_mrr"], name="MRR ex-largest",
            mode="lines+markers", line=dict(color=TEAL, width=2, dash="dot", shape="spline"),
            marker=dict(size=5, color=TEAL),
            hovertemplate="<b>%{x|%b}</b><br>MRR ex-whale $%{y:,.0f}<extra></extra>",
        )
    )
    fig.update_xaxes(tickformat="%b", dtick="M1")
    fig.update_yaxes(tickprefix="$", tickformat="~s")
    return fig


def concentration_chart(current: pd.DataFrame) -> go.Figure:
    ranked = current.sort_values("mrr", ascending=False).reset_index(drop=True)
    display = ranked.head(6)[["customer", "mrr"]].copy()
    rest = ranked.iloc[6:]["mrr"].sum()
    remaining_count = max(len(ranked) - 6, 0)
    display.loc[len(display)] = [f"Remaining {remaining_count:,}", rest]
    display = display.sort_values("mrr", ascending=True)
    total = float(current["mrr"].sum())
    top_customer = str(ranked.iloc[0]["customer"]) if not ranked.empty else None
    colors = [RED if customer == top_customer else LIGHT_BLUE for customer in display["customer"]]
    fig = chart_base()
    fig.add_trace(
        go.Bar(
            x=display["mrr"], y=display["customer"], orientation="h",
            marker=dict(color=colors, line=dict(color="rgba(255,255,255,.12)", width=1)),
            text=[f"{value / total:.0%}" for value in display["mrr"]], textposition="inside",
            insidetextanchor="end", textfont=dict(color=WHITE, size=9),
            hovertemplate="<b>%{y}</b><br>MRR $%{x:,.0f}<extra></extra>",
        )
    )
    fig.update_xaxes(tickprefix="$", tickformat="~s")
    fig.update_layout(showlegend=False, margin=dict(l=8, r=10, t=18, b=28))
    return fig


def bridge_chart(opening: float, expansion: float, losses: float, closing: float) -> go.Figure:
    fig = chart_base()
    fig.add_trace(
        go.Waterfall(
            x=["Opening", "Expansion", "Losses", "Closing"],
            y=[opening, expansion, losses, closing],
            measure=["absolute", "relative", "relative", "total"],
            connector=dict(line=dict(color="rgba(255,255,255,.18)", width=1)),
            increasing=dict(marker=dict(color=GREEN)),
            decreasing=dict(marker=dict(color=RED)),
            totals=dict(marker=dict(color=LIGHT_BLUE)),
            text=[money(opening, True), money(expansion, True, True), money(losses, True, True), money(closing, True)],
            textposition="outside", textfont=dict(color=WHITE, size=9),
            hovertemplate="<b>%{x}</b><br>%{text}<extra></extra>",
        )
    )
    fig.update_yaxes(tickprefix="$", tickformat="~s")
    fig.update_layout(showlegend=False)
    return fig


def account_health_chart(current: pd.DataFrame) -> go.Figure:
    ranked = current.sort_values("previous_mrr", ascending=False).head(350).copy()
    churned = current[current["churn_flag"].astype(bool)].nlargest(100, "previous_mrr")
    merged = pd.concat([ranked, churned], ignore_index=True).drop_duplicates("account_id")
    merged["growth"] = merged.apply(
        lambda row: (row["current_mrr"] / row["previous_mrr"] - 1) if row["previous_mrr"] else 0,
        axis=1,
    ).clip(-1, 2)
    merged["status"] = merged["growth"].apply(lambda value: "Growing" if value >= 0 else "Declining / churned")
    fig = chart_base()
    for status, color in [("Growing", GREEN), ("Declining / churned", RED)]:
        subset = merged[merged["status"].eq(status)]
        fig.add_trace(
            go.Scatter(
                x=subset["previous_mrr"], y=subset["growth"], name=status,
                mode="markers", text=subset["customer"],
                marker=dict(
                    color=color,
                    size=(subset["current_mrr"].clip(lower=10).pow(.5) * 1.2).clip(lower=6, upper=22),
                    line=dict(color=WHITE, width=1), opacity=.86,
                ),
                hovertemplate="<b>%{text}</b><br>Prior MRR $%{x:,.0f}<br>Growth %{y:+.1%}<extra></extra>",
            )
        )
    fig.add_hline(y=0, line_color="rgba(255,255,255,.25)", line_width=1)
    fig.update_xaxes(title="Prior MRR", title_font=dict(size=9), tickprefix="$", tickformat="~s")
    fig.update_yaxes(title="Growth", title_font=dict(size=9), tickformat="+.0%")
    return fig


def risk_donut(top_share: float, is_risk: bool) -> go.Figure:
    indicator_color = RED if is_risk else GREEN
    fig = go.Figure(
        go.Pie(
            values=[top_share, 1 - top_share], labels=["Top customer", "All others"],
            hole=.76, sort=False, direction="clockwise",
            marker=dict(colors=[indicator_color, DARK_BLUE], line=dict(color=BLACK, width=3)),
            textinfo="none", hovertemplate="<b>%{label}</b><br>%{percent}<extra></extra>",
        )
    )
    fig.add_annotation(
        text=f"<b>{top_share:.0%}</b><br><span style='font-size:9px'>TOP 1</span>",
        x=.5, y=.5, showarrow=False, font=dict(color=indicator_color, size=20),
    )
    fig.update_layout(
        height=148, margin=dict(l=2, r=2, t=2, b=2), showlegend=False,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig


@st.cache_data(show_spinner=False)
def load_risk_result(path: Path):
    result = analyze_account_risk(path)
    return result.accounts, result.risk_amplifier_ranking, result.json_graph_data


def risk_network_chart(graph_data: dict) -> go.Figure:
    """Force-directed layout of the risk graph: risk sources (red) ->
    financial consequences (amber) -> accounts (blue, sized by MRR)."""
    graph = nx.node_link_graph(graph_data, edges="links")
    pos = nx.spring_layout(graph, seed=7, k=0.6)

    edge_x, edge_y = [], []
    for u, v in graph.edges():
        edge_x += [pos[u][0], pos[v][0], None]
        edge_y += [pos[u][1], pos[v][1], None]

    node_x, node_y, node_color, node_size, node_text = [], [], [], [], []
    for node, data in graph.nodes(data=True):
        node_x.append(pos[node][0])
        node_y.append(pos[node][1])
        kind = data.get("kind")
        if kind == "risk_source":
            node_color.append(RED); node_size.append(22)
        elif kind == "financial_consequence":
            node_color.append("#F5A623"); node_size.append(18)
        else:
            node_color.append(LIGHT_BLUE); node_size.append(10)
        node_text.append(node)

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=edge_x, y=edge_y, mode="lines",
                              line=dict(color="rgba(255,255,255,.18)", width=1), hoverinfo="none"))
    fig.add_trace(go.Scatter(
        x=node_x, y=node_y, mode="markers", text=node_text, hovertemplate="<b>%{text}</b><extra></extra>",
        marker=dict(color=node_color, size=node_size, line=dict(color=WHITE, width=1)),
    ))
    fig.update_layout(
        showlegend=False, height=420, margin=dict(l=4, r=4, t=4, b=4),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return fig


_CLAIM_WORDS = ("broad-based", "broad based", "everyone", "across the board", "widespread",
                "true that", "is it true", "flat", "unchanged", "steady")


def agent_answer(
    question: str,
    stats: dict[str, object],
    engine: FinanceEngine,
    memory: MemoryStore,
    current_period: str,
    comparison_period: str,
) -> str:
    """Answers using the real backend -- investigate_variance() (Role 2's
    explanation engine, LLM-backed if ANTHROPIC_API_KEY is set) and
    verify_narrative_claim() (the "investor call" fact-checker) -- instead
    of a fixed keyword-templated string."""
    q = question.lower().strip()
    portfolio = engine.get_portfolio_variance(current_period, comparison_period)

    if any(word in q for word in _CLAIM_WORDS):
        verdict = verify_narrative_claim(question, portfolio, engine)
        icon = {"supported": "✅", "contradicted": "🚨", "partially_supported": "⚠️",
                "unsupported": "❌", "unverifiable": "❓"}.get(verdict.verdict, "")
        return f"{icon} **{verdict.verdict.replace('_', ' ').title()}** — {verdict.reasoning}"

    if any(word in q for word in ("whale", "concentration", "risk", "fragile")):
        drivers = engine.breakdown_variance(portfolio.variance_id, dimension="account", top_n=1)
        if drivers:
            top_variance = next(
                v for v in engine.compare_periods(current_period, comparison_period)
                if v.account == drivers[0].entity
            )
            explanation = investigate_variance(top_variance, engine, period=current_period, memory=memory)
            return explanation.explanation
        return f"{stats['whale']} contributes {stats['top_share']:.0%} of MRR."

    if any(word in q for word in ("churn", "lost", "customer")):
        churned = [v for v in engine.compare_periods(current_period, comparison_period)
                   if v.current == 0 and v.previous > 0]
        if churned:
            worst = max(churned, key=lambda v: v.previous)
            explanation = investigate_variance(worst, engine, period=current_period, memory=memory)
            return explanation.explanation
        return (
            f"Gross negative movement was {money(abs(float(stats['losses'])), True)} across the portfolio. "
            f"The full-account churn count was {stats['churned']}."
        )

    if any(word in q for word in ("revenue", "growth", "baseline", "mrr")):
        drivers = engine.breakdown_variance(portfolio.variance_id, dimension="account", top_n=3)
        from backend.agent_engine.explain import generate_explanation
        explanation = generate_explanation(
            portfolio, drivers, named_share=1.0,
            transaction_ids=[], historical_note=None,
        )
        return explanation.explanation

    if any(word in q for word in ("action", "recommend", "do", "next")):
        return "Protect the top-account renewal, investigate the recent full-account churns, and set a Top-1 concentration target below 35%."

    return "Ask about the whale, hidden churn, revenue quality, the next CFO action, or fact-check a claim (e.g. \"was growth broad-based?\")."


st.markdown(
    """
    <style>
    :root { --black:#000; --navy:#184D87; --blue:#33A1DD; --teal:#3AC0EF; --white:#fff; --green:#35D07F; --red:#FF5C6C; }
    * { box-sizing:border-box; }
    html, body, [class*="css"] { font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif; }
    .stApp { color:var(--white); background:radial-gradient(circle at 82% -8%,rgba(58,192,239,.13),transparent 27rem),radial-gradient(circle at -8% 52%,rgba(24,77,135,.18),transparent 28rem),var(--black); }
    header[data-testid="stHeader"] { background:transparent; height:0; }
    #MainMenu,footer,[data-testid="stToolbar"],[data-testid="stDecoration"] { display:none!important; }
    .block-container { max-width:none!important; width:100%!important; padding:.72rem 1.25rem 1.2rem!important; }
    [data-testid="stVerticalBlock"] { gap:.52rem; }
    [data-testid="stHorizontalBlock"] { align-items:stretch; gap:.65rem; }
    h1,h2,h3,p { color:var(--white); }

    .topbar { height:58px; display:flex; align-items:center; justify-content:space-between; border-bottom:1px solid rgba(51,161,221,.18); }
    .brand { display:flex; align-items:center; gap:.55rem; }
    .brand-logo { width:46px; height:46px; display:grid; place-items:center; overflow:hidden; border-radius:50%; }
    .brand-logo img { width:46px; height:46px; object-fit:contain; transform:scale(1.72); }
    .brand-name { font-size:1.28rem; line-height:1; font-weight:850; letter-spacing:-.045em; }
    .brand-name span { color:var(--teal); }
    .tagline { margin-top:.23rem; color:rgba(255,255,255,.52); font-size:.65rem; }
    .top-actions { display:flex; align-items:center; gap:.55rem; }
    .period-pill,.live-pill { padding:.4rem .62rem; border:1px solid rgba(51,161,221,.20); border-radius:999px; background:rgba(24,77,135,.16); color:rgba(255,255,255,.62); font-size:.55rem; font-weight:750; letter-spacing:.07em; }
    .live-pill { color:var(--teal); }
    .pulse { display:inline-block; width:6px; height:6px; margin-right:.36rem; border-radius:50%; background:var(--teal); box-shadow:0 0 0 4px rgba(58,192,239,.12); animation:pulse 1.8s infinite; }
    @keyframes pulse { 50% { box-shadow:0 0 0 8px rgba(58,192,239,0); } }

    .section-line { display:flex; align-items:end; justify-content:space-between; min-height:46px; padding-top:.12rem; }
    .eyebrow { color:var(--teal); text-transform:uppercase; letter-spacing:.15em; font-size:.52rem; font-weight:850; }
    .section-title { margin:.13rem 0 0; color:var(--white); font-size:1.03rem; font-weight:780; letter-spacing:-.025em; }
    .section-sub { color:rgba(255,255,255,.43); font-size:.6rem; }
    div[data-baseweb="select"]>div { min-height:35px; color:var(--white); background:rgba(24,77,135,.18); border-color:rgba(51,161,221,.28); font-size:.67rem; }
    ul[role="listbox"] { background:var(--black); border:1px solid var(--teal); }
    li[role="option"] { color:var(--white); }

    .metric-card { height:92px; padding:.66rem .75rem; border:1px solid rgba(51,161,221,.20); border-radius:12px; background:linear-gradient(145deg,rgba(24,77,135,.20),rgba(0,0,0,.76)); box-shadow:0 14px 36px rgba(0,0,0,.34); position:relative; overflow:hidden; }
    .metric-card:after { content:""; position:absolute; left:0; bottom:0; width:100%; height:2px; background:var(--blue); }
    .metric-card.positive:after { background:var(--green); }
    .metric-card.risk:after { background:var(--red); }
    .metric-head { display:flex; align-items:center; justify-content:space-between; color:rgba(255,255,255,.46); font-size:.49rem; font-weight:850; letter-spacing:.1em; text-transform:uppercase; }
    .metric-head i { width:19px; height:19px; display:grid; place-items:center; color:var(--teal); background:rgba(58,192,239,.09); border:1px solid rgba(58,192,239,.17); border-radius:6px; font-size:.57rem; font-style:normal; }
    .metric-card.positive .metric-head i,.metric-card.positive .metric-detail b { color:var(--green); }
    .metric-card.risk .metric-head i,.metric-card.risk .metric-detail b { color:var(--red); }
    .metric-value { margin:.35rem 0 .18rem; color:var(--white); font-size:1.22rem; line-height:1; font-weight:850; letter-spacing:-.04em; }
    .metric-detail { color:rgba(255,255,255,.44); font-size:.55rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
    .metric-detail b { color:var(--teal); }

    .st-key-chart_panel,.st-key-chart_panel_2,.st-key-chart_panel_3,.st-key-chart_panel_4,.st-key-agent_panel { border:1px solid rgba(51,161,221,.18); border-radius:14px; background:linear-gradient(145deg,rgba(24,77,135,.14),rgba(0,0,0,.66)); box-shadow:0 16px 42px rgba(0,0,0,.34); overflow:hidden; }
    .st-key-chart_panel,.st-key-chart_panel_2,.st-key-chart_panel_3,.st-key-chart_panel_4 { padding:.68rem .72rem .38rem; }
    .chart-heading { display:flex; justify-content:space-between; align-items:center; }
    .chart-title { color:var(--white); font-size:.75rem; font-weight:750; }
    .chart-meta { color:rgba(255,255,255,.34); font-size:.49rem; letter-spacing:.06em; text-transform:uppercase; }
    div[data-testid="stPlotlyChart"] { background:transparent!important; }

    .st-key-agent_panel { min-height:calc(100vh - 165px); padding:.75rem; border-color:rgba(58,192,239,.31); background:linear-gradient(165deg,rgba(24,77,135,.37),rgba(0,0,0,.91) 48%); }
    .st-key-agent_panel>div[data-testid="stVerticalBlock"] { min-height:calc(100vh - 190px); }
    .agent-head { display:flex; justify-content:space-between; align-items:start; padding-bottom:.55rem; border-bottom:1px solid rgba(255,255,255,.10); }
    .agent-title { color:var(--white); font-size:.82rem; font-weight:820; }
    .agent-sub { margin-top:.1rem; color:rgba(255,255,255,.42); font-size:.54rem; }
    .agent-badge { color:var(--teal); font-size:.48rem; font-weight:850; letter-spacing:.08em; }
    .risk-summary { display:grid; grid-template-columns:42% 58%; align-items:center; margin:.35rem 0 .4rem; }
    .risk-copy strong { display:block; color:var(--red); font-size:.8rem; }
    .risk-copy.positive strong { color:var(--green); }
    .risk-copy span { display:block; margin-top:.16rem; color:rgba(255,255,255,.50); font-size:.53rem; line-height:1.38; }
    .story-step { display:grid; grid-template-columns:22px 1fr; gap:.45rem; padding:.42rem 0; border-top:1px solid rgba(255,255,255,.08); }
    .story-step i { width:20px; height:20px; display:grid; place-items:center; color:var(--teal); background:rgba(58,192,239,.09); border:1px solid rgba(58,192,239,.17); border-radius:6px; font-size:.48rem; font-style:normal; font-weight:850; }
    .story-step.risk i { color:var(--red); border-color:rgba(255,92,108,.28); background:rgba(255,92,108,.08); }
    .story-step.positive i { color:var(--green); border-color:rgba(53,208,127,.25); background:rgba(53,208,127,.07); }
    .story-label { color:rgba(255,255,255,.42); font-size:.46rem; font-weight:850; letter-spacing:.1em; text-transform:uppercase; }
    .story-text { margin-top:.1rem; color:rgba(255,255,255,.73); font-size:.57rem; line-height:1.38; }
    .story-text b { color:var(--white); }
    .story-step.risk .story-text b { color:var(--red); }
    .story-step.positive .story-text b { color:var(--green); }
    .message-user,.message-agent { padding:.45rem .52rem; font-size:.56rem; line-height:1.4; border:1px solid rgba(255,255,255,.09); }
    .message-user { margin:.38rem 0 .25rem 18%; color:var(--white); background:var(--blue); border-radius:9px 9px 3px 9px; }
    .message-agent { margin:.25rem 8% .25rem 0; color:rgba(255,255,255,.74); background:rgba(255,255,255,.055); border-radius:9px 9px 9px 3px; }
    .st-key-agent_panel [data-testid="stForm"] { border:0; padding:0; margin-top:auto; }
    .st-key-agent_panel .stTextInput input { min-height:32px; color:var(--white)!important; background:rgba(255,255,255,.055)!important; border:1px solid rgba(255,255,255,.14)!important; border-radius:8px!important; font-size:.58rem!important; }
    .st-key-agent_panel .stTextInput input::placeholder { color:rgba(255,255,255,.34)!important; }
    .st-key-agent_panel .stButton button { min-height:30px; width:100%; color:var(--white); background:var(--blue); border:1px solid var(--teal); border-radius:8px; font-size:.57rem; font-weight:820; }
    [data-testid="stCaptionContainer"] { color:rgba(255,255,255,.29); font-size:.47rem; }
    .loader-card { min-height:72vh; display:flex; flex-direction:column; align-items:center; justify-content:center; text-align:center; }
    .loader-card img { width:116px; height:116px; object-fit:contain; transform:scale(1.65); animation:whale-float 1.8s ease-in-out infinite; filter:drop-shadow(0 0 24px rgba(58,192,239,.30)); }
    .loader-card strong { margin-top:.8rem; color:var(--white); font-size:1rem; }
    .loader-card span { margin-top:.3rem; color:rgba(255,255,255,.48); font-size:.67rem; }
    .loader-line { width:210px; height:3px; margin-top:1rem; overflow:hidden; border-radius:99px; background:rgba(255,255,255,.08); }
    .loader-line i { display:block; width:45%; height:100%; border-radius:99px; background:linear-gradient(90deg,var(--blue),var(--teal)); animation:loader-scan 1.25s ease-in-out infinite; }
    @keyframes whale-float { 50% { transform:scale(1.65) translateY(-5px); } }
    @keyframes loader-scan { from { transform:translateX(-110%); } to { transform:translateX(245%); } }

    /* -- API key bar (Overview tab) -- */
    .st-key-apikey_panel { border:1px solid rgba(51,161,221,.20); border-radius:12px; background:linear-gradient(145deg,rgba(24,77,135,.16),rgba(0,0,0,.7)); padding:.6rem .9rem; margin-bottom:.9rem; }
    .apikey-row { display:flex; align-items:center; gap:.7rem; }
    .apikey-label { display:flex; align-items:center; gap:.4rem; color:rgba(255,255,255,.62); font-size:.6rem; font-weight:750; letter-spacing:.06em; text-transform:uppercase; white-space:nowrap; }
    .llm-status { display:flex; align-items:center; gap:.35rem; font-size:.56rem; font-weight:800; letter-spacing:.06em; text-transform:uppercase; padding:.28rem .6rem; border-radius:999px; white-space:nowrap; }
    .llm-status.on { color:var(--green); background:rgba(53,208,127,.10); border:1px solid rgba(53,208,127,.28); }
    .llm-status.off { color:rgba(255,255,255,.42); background:rgba(255,255,255,.05); border:1px solid rgba(255,255,255,.12); }
    .llm-status .dot { width:5px; height:5px; border-radius:50%; background:currentColor; }
    .st-key-apikey_panel .stTextInput input { min-height:32px; color:var(--white)!important; background:rgba(255,255,255,.06)!important; border:1px solid rgba(255,255,255,.16)!important; border-radius:8px!important; font-size:.62rem!important; }

    /* -- shared panel styling for Risk Graph / Fact-Check tabs -- */
    .st-key-chart_panel_risk_amp,.st-key-chart_panel_risk_net,.st-key-chart_panel_risk_story,
    .st-key-chart_panel_risk_table,.st-key-chart_panel_risk_trace,.st-key-factcheck_input,.st-key-factcheck_history {
      border:1px solid rgba(51,161,221,.18); border-radius:14px;
      background:linear-gradient(145deg,rgba(24,77,135,.14),rgba(0,0,0,.66));
      box-shadow:0 16px 42px rgba(0,0,0,.34); overflow:hidden; padding:.7rem .75rem .5rem;
    }

    /* -- KPI strip (Risk Graph tab) -- */
    .kpi-strip { display:grid; grid-template-columns:repeat(4,1fr); gap:.6rem; margin-bottom:.85rem; }
    .kpi-tile { padding:.62rem .72rem; border-radius:11px; border:1px solid rgba(51,161,221,.18); background:linear-gradient(145deg,rgba(24,77,135,.16),rgba(0,0,0,.7)); }
    .kpi-tile .kpi-label { color:rgba(255,255,255,.46); font-size:.48rem; font-weight:800; letter-spacing:.09em; text-transform:uppercase; }
    .kpi-tile .kpi-value { margin-top:.28rem; font-size:1.1rem; font-weight:850; color:var(--white); letter-spacing:-.03em; }
    .kpi-tile .kpi-sub { margin-top:.1rem; font-size:.52rem; color:rgba(255,255,255,.4); }
    .kpi-tile.crit .kpi-value { color:var(--red); }
    .kpi-tile.warn .kpi-value { color:var(--teal); }

    /* -- severity pills + risk table -- */
    .sev-pill { display:inline-flex; align-items:center; gap:.3rem; padding:.16rem .5rem; border-radius:999px; font-size:.5rem; font-weight:800; letter-spacing:.06em; text-transform:uppercase; }
    .sev-pill.critical { color:var(--red); background:rgba(255,92,108,.12); border:1px solid rgba(255,92,108,.3); }
    .sev-pill.elevated { color:#f5c451; background:rgba(245,196,81,.10); border:1px solid rgba(245,196,81,.28); }
    .sev-pill.normal { color:var(--teal); background:rgba(58,192,239,.09); border:1px solid rgba(58,192,239,.22); }
    .risk-row { display:grid; grid-template-columns:1.1fr .9fr 1.3fr .9fr; align-items:center; gap:.5rem; padding:.5rem .15rem; border-top:1px solid rgba(255,255,255,.07); font-size:.63rem; }
    .risk-row.head { color:rgba(255,255,255,.4); font-size:.5rem; font-weight:800; letter-spacing:.08em; text-transform:uppercase; border-top:none; padding-bottom:.35rem; }
    .risk-row .acct { font-weight:750; color:var(--white); }
    .risk-row .score { font-variant-numeric:tabular-nums; color:var(--teal); }
    .risk-row .driver { color:rgba(255,255,255,.6); }

    /* -- risk narrative story card -- */
    .risk-story-head { display:flex; justify-content:space-between; align-items:baseline; margin-bottom:.4rem; }
    .risk-story-head .t { font-size:.75rem; font-weight:750; color:var(--white); }
    .risk-story-head .s { font-size:.5rem; color:rgba(255,255,255,.4); text-transform:uppercase; letter-spacing:.07em; }

    /* -- fact-check hero verdict card -- */
    .verdict-hero { display:grid; grid-template-columns:auto 1fr; gap:1rem; align-items:center; padding:1rem 1.1rem; border-radius:14px; margin:.8rem 0; border:1px solid; }
    .verdict-hero.supported { background:linear-gradient(135deg,rgba(53,208,127,.14),rgba(0,0,0,.5)); border-color:rgba(53,208,127,.35); }
    .verdict-hero.contradicted { background:linear-gradient(135deg,rgba(255,92,108,.14),rgba(0,0,0,.5)); border-color:rgba(255,92,108,.35); }
    .verdict-hero.partially_supported,.verdict-hero.unsupported { background:linear-gradient(135deg,rgba(245,196,81,.14),rgba(0,0,0,.5)); border-color:rgba(245,196,81,.32); }
    .verdict-hero.unverifiable { background:linear-gradient(135deg,rgba(255,255,255,.06),rgba(0,0,0,.5)); border-color:rgba(255,255,255,.16); }
    .verdict-hero .icon { font-size:2.1rem; line-height:1; }
    .verdict-hero .label { font-size:1.05rem; font-weight:850; letter-spacing:-.01em; }
    .verdict-hero .reason { margin-top:.3rem; font-size:.72rem; color:rgba(255,255,255,.72); line-height:1.45; }

    .meter { height:7px; border-radius:99px; background:rgba(255,255,255,.09); overflow:hidden; margin-top:.5rem; }
    .meter i { display:block; height:100%; border-radius:99px; background:linear-gradient(90deg,var(--blue),var(--teal)); }
    .meter-label { display:flex; justify-content:space-between; font-size:.52rem; color:rgba(255,255,255,.42); margin-top:.25rem; text-transform:uppercase; letter-spacing:.06em; }

    .evidence-chip-row { display:flex; flex-wrap:wrap; gap:.35rem; margin-top:.35rem; }
    .evidence-chip { font-family:monospace; font-size:.56rem; padding:.2rem .5rem; border-radius:6px; background:rgba(255,255,255,.06); border:1px solid rgba(255,255,255,.13); color:rgba(255,255,255,.68); }

    .history-item { display:grid; grid-template-columns:16px 1fr auto; gap:.5rem; align-items:start; padding:.45rem 0; border-top:1px solid rgba(255,255,255,.07); font-size:.6rem; }
    .history-item:first-child { border-top:none; }
    .history-item .claim { color:rgba(255,255,255,.68); }
    .history-item .badge { font-size:.48rem; font-weight:800; letter-spacing:.05em; text-transform:uppercase; padding:.12rem .4rem; border-radius:5px; white-space:nowrap; }

    @media(max-width:900px) {
      .block-container { padding:.6rem!important; }
      .tagline,.period-pill { display:none; }
      [data-testid="stHorizontalBlock"] { flex-wrap:wrap; }
      [data-testid="stHorizontalBlock"]>[data-testid="stColumn"] { min-width:calc(50% - .5rem); }
      .st-key-agent_panel { min-height:auto; }
      .st-key-agent_panel>div[data-testid="stVerticalBlock"] { min-height:auto; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


if not DATA_PATH.exists():
    st.error(f"Dataset not found at {DATA_PATH}. Run: python3 data/generate_subscription_data.py")
    st.stop()

loader = st.empty()
loader.markdown(
    f"<div class='loader-card'><img src='{image_data_uri(LOGO_PATH)}' alt='WhaleWatch loading'>"
    "<strong>WhaleWatch is scanning your revenue ocean</strong>"
    "<span>Aggregating accounts, identifying whales, and measuring hidden churn…</span>"
    "<div class='loader-line'><i></i></div></div>",
    unsafe_allow_html=True,
)
monthly, current = load_real_data(DATA_PATH)
engine, memory = load_engine()
loader.empty()
if monthly.empty or current.empty:
    st.error(f"{DATA_PATH} did not contain usable monthly account records.")
    st.stop()

latest_month = monthly.iloc[-1]
current_period = month_to_period(int(latest_month["month"]))
comparison_period = month_to_period(int(monthly.iloc[-2]["month"])) if len(monthly) > 1 else current_period
current_total = float(latest_month["total_mrr"])
previous_total = float(latest_month["previous_mrr"])
growth = current_total / previous_total - 1 if previous_total else 0
ranked = current.sort_values("mrr", ascending=False).reset_index(drop=True)
whale = str(ranked.iloc[0]["customer"])
whale_mrr = float(ranked.iloc[0]["mrr"])
previous_whale = float(ranked.iloc[0]["previous_mrr"]) if pd.notna(ranked.iloc[0]["previous_mrr"]) else 0
top_share = whale_mrr / current_total if current_total else 0
top_five_share = float(ranked.head(5)["mrr"].sum()) / current_total if current_total else 0
organic_current = current_total - whale_mrr
organic_previous = previous_total - previous_whale
organic_growth = organic_current / organic_previous - 1 if organic_previous else 0
churned = int(latest_month["churned"])
losses = float(latest_month["losses"])
expansion = float(latest_month["expansion"])
hhi = float(((current["mrr"] / current_total) ** 2).sum()) if current_total else 0
customer_count = int(current["account_id"].nunique())
period_label = str(latest_month["month_label"])
concentration_risk = top_share >= .25
risk_level = "High concentration risk" if concentration_risk else "Low concentration risk"
story_class = "risk" if concentration_risk else "positive"
real_story = (
    f"Revenue is fragile: one non-renewal removes {money(whale_mrr, True)} in MRR."
    if concentration_risk
    else f"Revenue is diversified across {customer_count:,} accounts; churn is the larger near-term risk."
)

stats: dict[str, object] = {
    "whale": whale, "whale_mrr": whale_mrr, "top_share": top_share,
    "churned": churned, "losses": losses, "current_total": current_total,
    "growth": growth, "organic_growth": organic_growth,
}

st.markdown(
    f"""
    <div class="topbar">
      <div class="brand"><div class="brand-logo"><img src="{image_data_uri(LOGO_PATH)}" alt="WhaleWatch logo"></div>
        <div><div class="brand-name">Whale<span>Watch</span></div>
        <div class="tagline">Don't just track revenue. Track the whales driving it.</div></div>
      </div>
      <div class="top-actions"><div class="period-pill">CFO COMMAND CENTER · {period_label.upper()}</div>
      <div class="live-pill"><span class="pulse"></span>LIVE · {datetime.now().strftime('%I:%M %p')}</div></div>
    </div>
    """,
    unsafe_allow_html=True,
)

tab_overview, tab_risk, tab_check = st.tabs(["📊 Overview", "🕸️ Risk Graph", "📞 Investor Call Fact-Check"])

with tab_overview:
    with st.container(key="apikey_panel"):
        key_col, status_col = st.columns([5, 1.4])
        with key_col:
            st.markdown("<div class='apikey-row'><span class='apikey-label'>🔑 Anthropic API key</span></div>", unsafe_allow_html=True)
            entered_key = st.text_input(
                "Anthropic API key", type="password", label_visibility="collapsed",
                value=st.session_state.get("anthropic_api_key", ""),
                placeholder="sk-ant-... (optional -- leave blank to use the built-in template narrator)",
                key="anthropic_api_key_input",
            )
            if entered_key != st.session_state.get("anthropic_api_key", ""):
                st.session_state["anthropic_api_key"] = entered_key
                if entered_key:
                    os.environ["ANTHROPIC_API_KEY"] = entered_key
                else:
                    os.environ.pop("ANTHROPIC_API_KEY", None)
                st.rerun()
        with status_col:
            llm_on = bool(os.environ.get("ANTHROPIC_API_KEY"))
            st.markdown(
                f"<div style='padding-top:1.15rem'><span class='llm-status {'on' if llm_on else 'off'}'>"
                f"<span class='dot'></span>{'LLM connected' if llm_on else 'Template mode'}</span></div>",
                unsafe_allow_html=True,
            )

    title_col, selector_col = st.columns([5, 1.35])
    with title_col:
        st.markdown(
            "<div class='section-line'><div><div class='eyebrow'>Revenue quality & concentration</div>"
            "<div class='section-title'>Growth is good. Durable growth is better.</div></div>"
            f"<div class='section-sub'>Portfolio view · {customer_count:,} accounts · Source: data/subscription_accounts.csv</div></div>",
            unsafe_allow_html=True,
        )
    with selector_col:
        st.selectbox("Reporting period", [period_label], label_visibility="collapsed")

    k1, k2, k3, k4, k5, k6 = st.columns(6)
    with k1:
        st.markdown(metric_card("Total MRR", money(current_total, True), f"<b>{percentage(growth, True)}</b> vs last month", "$", "positive" if growth >= 0 else "risk"), unsafe_allow_html=True)
    with k2:
        st.markdown(metric_card("MRR ex-whale", money(organic_current, True), f"<b>{percentage(organic_growth, True)}</b> underlying growth", "↘", "positive" if organic_growth >= 0 else "risk"), unsafe_allow_html=True)
    with k3:
        st.markdown(metric_card("Top 1 exposure", percentage(top_share), f"<b>{money(whale_mrr, True)}</b> from {whale}", "!", "risk" if concentration_risk else "positive"), unsafe_allow_html=True)
    with k4:
        concentration_label = "High" if top_five_share >= .50 else "Diversified"
        concentration_state = "risk" if top_five_share >= .50 else "positive"
        st.markdown(metric_card("Top 5 exposure", percentage(top_five_share), f"<b>{concentration_label}</b> portfolio dependency", "5", concentration_state), unsafe_allow_html=True)
    with k5:
        st.markdown(metric_card("Gross MRR loss", money(abs(losses), True), f"<b>{churned}</b> full-account churns", "−", "risk" if losses < 0 else "positive"), unsafe_allow_html=True)
    with k6:
        hhi_label = "Concentrated" if hhi > .18 else "Diversified"
        st.markdown(metric_card("HHI score", f"{hhi * 10_000:,.0f}", f"<b>{hhi_label}</b> revenue base", "H", "risk" if hhi > .18 else "positive"), unsafe_allow_html=True)

    charts_col, agent_col = st.columns([2, 1], gap="medium")
    with charts_col:
        top_left, top_right = st.columns([1.25, 1])
        with top_left:
            with st.container(key="chart_panel"):
                st.markdown("<div class='chart-heading'><div class='chart-title'>Revenue quality</div><div class='chart-meta'>Total vs ex-whale</div></div>", unsafe_allow_html=True)
                st.plotly_chart(revenue_quality_chart(monthly), width="stretch", config={"displayModeBar": False})
        with top_right:
            with st.container(key="chart_panel_2"):
                st.markdown("<div class='chart-heading'><div class='chart-title'>Customer concentration</div><div class='chart-meta'>Latest MRR share</div></div>", unsafe_allow_html=True)
                st.plotly_chart(concentration_chart(current), width="stretch", config={"displayModeBar": False})

        bottom_left, bottom_right = st.columns(2)
        with bottom_left:
            with st.container(key="chart_panel_3"):
                st.markdown("<div class='chart-heading'><div class='chart-title'>MRR movement bridge</div><div class='chart-meta'>Month over month</div></div>", unsafe_allow_html=True)
                st.plotly_chart(bridge_chart(previous_total, expansion, losses, current_total), width="stretch", config={"displayModeBar": False})
        with bottom_right:
            with st.container(key="chart_panel_4"):
                st.markdown("<div class='chart-heading'><div class='chart-title'>Customer growth map</div><div class='chart-meta'>Size × momentum</div></div>", unsafe_allow_html=True)
                st.plotly_chart(account_health_chart(current), width="stretch", config={"displayModeBar": False})

    with agent_col:
        with st.container(key="agent_panel"):
            st.markdown(
                "<div class='agent-head'><div><div class='agent-title'>Concentration Risk Agent</div>"
                "<div class='agent-sub'>The story behind the headline</div></div>"
                "<div class='agent-badge'>● ONLINE</div></div>", unsafe_allow_html=True,
            )
            donut_col, risk_copy_col = st.columns([1, 1.35])
            with donut_col:
                st.plotly_chart(risk_donut(top_share, concentration_risk), width="stretch", config={"displayModeBar": False})
            with risk_copy_col:
                st.markdown(
                    f"<div class='risk-copy {'risk' if concentration_risk else 'positive'}'><strong>{risk_level}</strong>"
                    f"<span>{html.escape(whale)} controls {top_share:.0%} of recurring revenue. "
                    f"That is {money(whale_mrr, True)} of monthly exposure.</span></div>", unsafe_allow_html=True,
                )
            st.markdown(
                f"<div class='story-step positive'><i>1</i><div><div class='story-label'>Baseline</div>"
                f"<div class='story-text'>MRR reached <b>{money(current_total, True)}</b>, up <b>{percentage(growth, True)}</b> month over month.</div></div></div>"
                f"<div class='story-step {story_class}'><i>2</i><div><div class='story-label'>Largest account</div>"
                f"<div class='story-text'><b>{html.escape(whale)}</b> moved {money(whale_mrr - previous_whale, True, True)} and now represents <b>{top_share:.1%}</b> of MRR.</div></div></div>"
                f"<div class='story-step risk'><i>3</i><div><div class='story-label'>Hidden losses</div>"
                f"<div class='story-text'><b>{money(abs(losses), True)} gross negative movement</b> across the portfolio; {churned} full-account churns.</div></div></div>"
                f"<div class='story-step {story_class}'><i>4</i><div><div class='story-label'>The real story</div>"
                f"<div class='story-text'><b>{real_story}</b></div></div></div>",
                unsafe_allow_html=True,
            )

            if "agent_messages" not in st.session_state:
                st.session_state.agent_messages = [{"role": "agent", "content": "Ask me about the whale, hidden churn, or the next CFO action."}]
            for message in st.session_state.agent_messages[-2:]:
                css_class = "message-user" if message["role"] == "user" else "message-agent"
                st.markdown(f"<div class='{css_class}'>{html.escape(message['content'])}</div>", unsafe_allow_html=True)
            with st.form("agent_form", clear_on_submit=True):
                question = st.text_input("Ask the agent", placeholder="Ask what makes growth fragile…", label_visibility="collapsed")
                submitted = st.form_submit_button("Ask Concentration Agent", use_container_width=True)
            if submitted and question.strip():
                st.session_state.agent_messages.append({"role": "user", "content": question.strip()})
                answer = agent_answer(question, stats, engine, memory, current_period, comparison_period)
                st.session_state.agent_messages.append({"role": "agent", "content": answer})
                st.rerun()
            st.caption("Live portfolio analysis, powered by the WhyLedger backend")



with tab_risk:
    st.markdown(
        "<div class='section-line'><div><div class='eyebrow'>Systemic risk graph</div>"
        "<div class='section-title'>Which accounts sit downstream of the most operational risk?</div></div>"
        "<div class='section-sub'>Reliability incidents, support friction, and payment delays &rarr; financial "
        "consequences &rarr; accounts. Live PageRank over a directed graph (backend/risk_graph).</div></div>",
        unsafe_allow_html=True,
    )
    st.write("")

    risk_accounts, amplifier_ranking, graph_data = load_risk_result(DATA_PATH)
    n_accounts = len(risk_accounts)
    critical_cutoff = max(3, round(n_accounts * 0.06))
    traceable = int((risk_accounts["cascading_loss_paths"].map(len) > 0).sum())
    top_row = risk_accounts.iloc[0]
    top_driver_name, top_driver_val = amplifier_ranking[0]

    def _severity(rank: int) -> tuple[str, str]:
        if rank <= critical_cutoff:
            return "critical", "Critical"
        if rank <= critical_cutoff * 2:
            return "elevated", "Elevated"
        return "normal", "Normal"

    st.markdown(
        f"""<div class="kpi-strip">
          <div class="kpi-tile crit"><div class="kpi-label">Highest cascade risk</div>
            <div class="kpi-value">{top_row['account_id']}</div>
            <div class="kpi-sub">score {top_row['graph_pagerank_risk_score']:.4f}</div></div>
          <div class="kpi-tile"><div class="kpi-label">Top risk amplifier</div>
            <div class="kpi-value">{top_driver_name.replace('_',' ')}</div>
            <div class="kpi-sub">{money(top_driver_val, True)} downstream impact</div></div>
          <div class="kpi-tile warn"><div class="kpi-label">Critical accounts</div>
            <div class="kpi-value">{critical_cutoff}</div>
            <div class="kpi-sub">of {n_accounts} scored this period</div></div>
          <div class="kpi-tile"><div class="kpi-label">Traceable loss paths</div>
            <div class="kpi-value">{traceable}</div>
            <div class="kpi-sub">root cause &rarr; account confirmed</div></div>
        </div>""",
        unsafe_allow_html=True,
    )

    with st.container(key="chart_panel_risk_story"):
        top_path = max(
            (p for p in top_row["cascading_loss_paths"]), key=lambda p: p["total_weight"], default=None,
        )
        st.markdown(
            f"<div class='risk-story-head'><span class='t'>Why {top_row['account_id']} is the #1 systemic risk</span>"
            f"<span class='s'>Auto-generated from the traced graph</span></div>", unsafe_allow_html=True,
        )
        if top_path:
            source, mid, target = top_path["path"][0], top_path["path"][1], top_path["path"][-1]
            e1, e2 = top_path["edges"][0], top_path["edges"][1]
            st.markdown(
                f"<div class='story-step risk'><i>1</i><div><div class='story-label'>Operational trigger</div>"
                f"<div class='story-text'><b>{source.replace('_',' ')}</b> is active on this account, "
                f"driving <b>{money(e1['weight'], True)}</b> toward <b>{mid.replace('_',' ')}</b>.</div></div></div>"
                f"<div class='story-step risk'><i>2</i><div><div class='story-label'>Financial consequence</div>"
                f"<div class='story-text'><b>{mid.replace('_',' ')}</b> converts that into "
                f"<b>{e2['weight']:.1%} of {target}'s MRR</b> at risk.</div></div></div>"
                f"<div class='story-step positive'><i>3</i><div><div class='story-label'>Net effect</div>"
                f"<div class='story-text'>Combined weighted exposure: <b>{money(top_path['total_weight'], True)}</b> "
                f"&mdash; the largest traced chain in the portfolio this period.</div></div></div>",
                unsafe_allow_html=True,
            )
        else:
            st.caption("No traceable path for the top-ranked account this period.")

    st.write("")
    amp_col, net_col = st.columns([1, 1.55], gap="medium")
    with amp_col:
        with st.container(key="chart_panel_risk_amp"):
            st.markdown("<div class='chart-heading'><div class='chart-title'>Risk amplifier ranking</div>"
                        "<div class='chart-meta'>Weighted downstream $ impact</div></div>", unsafe_allow_html=True)
            amp_fig = chart_base()
            amp_colors = [RED, "#f5c451", TEAL]
            amp_fig.add_trace(go.Bar(
                x=[v for _, v in amplifier_ranking], y=[n.replace("_", " ") for n, _ in amplifier_ranking],
                orientation="h", marker=dict(color=amp_colors[:len(amplifier_ranking)]),
                text=[money(v, True) for _, v in amplifier_ranking], textposition="outside",
                textfont=dict(color=WHITE, size=9),
                hovertemplate="<b>%{y}</b><br>$%{x:,.0f}<extra></extra>",
            ))
            amp_fig.update_xaxes(tickprefix="$", tickformat="~s")
            amp_fig.update_layout(height=170, margin=dict(l=8, r=32, t=6, b=20), bargap=.35)
            st.plotly_chart(amp_fig, width="stretch", config={"displayModeBar": False})
    with net_col:
        with st.container(key="chart_panel_risk_net"):
            st.markdown("<div class='chart-heading'><div class='chart-title'>Risk flow graph</div>"
                        "<div class='chart-meta'>Risk source &rarr; consequence &rarr; account</div></div>", unsafe_allow_html=True)
            st.plotly_chart(risk_network_chart(graph_data), width="stretch", config={"displayModeBar": False})
            st.caption("🔴 Operational risk source &nbsp;·&nbsp; 🟠 Financial consequence &nbsp;·&nbsp; 🔵 Account")

    st.write("")
    with st.container(key="chart_panel_risk_table"):
        st.markdown("<div class='chart-heading'><div class='chart-title'>Top 10 accounts by Cascade Risk Index</div>"
                    "<div class='chart-meta'>PageRank, weighted</div></div>", unsafe_allow_html=True)
        st.markdown(
            "<div class='risk-row head'><div>Account</div><div>Cascade score</div><div>Primary driver</div><div>Severity</div></div>",
            unsafe_allow_html=True,
        )
        for rank, (_, r) in enumerate(risk_accounts.head(10).iterrows(), start=1):
            sev_class, sev_label = _severity(rank)
            st.markdown(
                f"<div class='risk-row'><div class='acct'>{r['account_id']}</div>"
                f"<div class='score'>{r['graph_pagerank_risk_score']:.4f}</div>"
                f"<div class='driver'>{(r['primary_risk_driver_node'] or '—').replace('_',' ')}</div>"
                f"<div><span class='sev-pill {sev_class}'>{sev_label}</span></div></div>",
                unsafe_allow_html=True,
            )

    st.write("")
    with st.container(key="chart_panel_risk_trace"):
        st.markdown("<div class='chart-heading'><div class='chart-title'>Trace a cascading loss path</div>"
                    "<div class='chart-meta'>Pick any account</div></div>", unsafe_allow_html=True)
        selected_account = st.selectbox("Pick an account", risk_accounts["account_id"].tolist(), key="risk_account_select", label_visibility="collapsed")
        row = risk_accounts[risk_accounts["account_id"] == selected_account].iloc[0]
        st.markdown(
            f"<div style='margin:.5rem 0'><span class='sev-pill normal'>Cascade {row['graph_pagerank_risk_score']:.4f}</span> "
            f"&nbsp; <span class='sev-pill elevated'>{(row['primary_risk_driver_node'] or 'No driver').replace('_',' ')}</span></div>",
            unsafe_allow_html=True,
        )
        if row["cascading_loss_paths"]:
            for path in row["cascading_loss_paths"]:
                chips = " &rarr; ".join(f"<span class='evidence-chip'>{p}</span>" for p in path["path"])
                st.markdown(f"<div style='margin:.35rem 0'>{chips} &nbsp; <span style='color:rgba(255,255,255,.4);font-size:.6rem'>weight {path['total_weight']:,.2f}</span></div>", unsafe_allow_html=True)
        else:
            st.caption("No traceable operational-risk path to this account.")


with tab_check:
    st.markdown(
        "<div class='section-line'><div><div class='eyebrow'>Narrative fact-check</div>"
        "<div class='section-title'>Does the story match the transactions?</div></div>"
        "<div class='section-sub'>Paste a line from an earnings call, investor update, or exec summary. "
        "Checked against real driver data -- never the LLM's own judgment "
        "(backend/agent_engine/narrative_check.py).</div></div>",
        unsafe_allow_html=True,
    )
    st.write("")

    if "factcheck_history" not in st.session_state:
        st.session_state.factcheck_history = []

    input_col, history_col = st.columns([1.6, 1], gap="medium")

    with input_col:
        with st.container(key="factcheck_input"):
            st.markdown("<div class='chart-heading'><div class='chart-title'>Check a claim</div>"
                        "<div class='chart-meta'>Scope + wording</div></div>", unsafe_allow_html=True)

            scope_options = ["Total Portfolio MRR"] + risk_accounts["account_id"].tolist()
            scope = st.selectbox("Check against", scope_options, key="factcheck_scope")

            st.markdown("<div style='margin-top:.5rem;font-size:.6rem;color:rgba(255,255,255,.45);"
                        "text-transform:uppercase;letter-spacing:.06em;font-weight:750'>Try one, or write your own</div>",
                        unsafe_allow_html=True)
            example_claims = [
                "Growth this month was broad-based across the customer base.",
                f"{whale} drove the entire increase this month.",
                "Revenue was flat month over month.",
            ]
            if "factcheck_claim" not in st.session_state:
                st.session_state.factcheck_claim = example_claims[0]
            ex_cols = st.columns(3)
            for col, claim in zip(ex_cols, example_claims):
                with col:
                    if st.button(claim, key=f"example_{claim[:12]}", use_container_width=True):
                        st.session_state.factcheck_claim = claim

            claim_text = st.text_area("Claim to check", key="factcheck_claim", height=80, label_visibility="collapsed")
            run_check = st.button("🔎 Check this claim", type="primary", use_container_width=True)

            if run_check and claim_text.strip():
                if scope == "Total Portfolio MRR":
                    variance = engine.get_portfolio_variance(current_period, comparison_period)
                else:
                    variance = next(
                        v for v in engine.compare_periods(current_period, comparison_period)
                        if v.account == scope
                    )
                verdict = verify_narrative_claim(claim_text.strip(), variance, engine)
                st.session_state["factcheck_last"] = verdict
                st.session_state.factcheck_history.insert(0, {
                    "claim": claim_text.strip(), "scope": scope, "verdict": verdict.verdict,
                })
                st.session_state.factcheck_history = st.session_state.factcheck_history[:6]

            verdict = st.session_state.get("factcheck_last")
            if verdict is not None:
                meta = {
                    "supported": ("✅", "Supported", "supported"),
                    "contradicted": ("🚨", "Contradicted", "contradicted"),
                    "partially_supported": ("⚠️", "Partially supported", "partially_supported"),
                    "unsupported": ("❌", "Unsupported", "unsupported"),
                    "unverifiable": ("❓", "Unverifiable", "unverifiable"),
                }.get(verdict.verdict, ("•", verdict.verdict.title(), "unverifiable"))
                icon, label, css_class = meta

                st.markdown(
                    f"<div class='verdict-hero {css_class}'><div class='icon'>{icon}</div>"
                    f"<div><div class='label'>{label}</div>"
                    f"<div class='reason'>{html.escape(verdict.reasoning)}</div></div></div>",
                    unsafe_allow_html=True,
                )

                if verdict.match_pct is not None:
                    pct = max(0.0, min(1.0, verdict.match_pct))
                    st.markdown(
                        f"<div class='meter'><i style='width:{pct*100:.0f}%'></i></div>"
                        f"<div class='meter-label'><span>Claimed entities' share of the change</span><span>{pct:.0%}</span></div>",
                        unsafe_allow_html=True,
                    )

                claimed = verdict.claimed_entities or verdict.matched_entities
                st.markdown(
                    "<div style='margin-top:.9rem;font-size:.6rem;color:rgba(255,255,255,.45);"
                    "text-transform:uppercase;letter-spacing:.06em;font-weight:750'>Evidence</div>",
                    unsafe_allow_html=True,
                )
                chip_html = lambda items: "".join(f"<span class='evidence-chip'>{html.escape(str(i))}</span>" for i in items) or "<span class='evidence-chip'>none</span>"
                st.markdown(
                    f"<div style='font-size:.62rem;color:rgba(255,255,255,.5);margin-top:.4rem'>Claim named</div>"
                    f"<div class='evidence-chip-row'>{chip_html(claimed)}</div>"
                    f"<div style='font-size:.62rem;color:rgba(255,255,255,.5);margin-top:.5rem'>Actual top drivers</div>"
                    f"<div class='evidence-chip-row'>{chip_html(verdict.actual_top_entities)}</div>"
                    f"<div style='font-size:.62rem;color:rgba(255,255,255,.5);margin-top:.5rem'>Transactions</div>"
                    f"<div class='evidence-chip-row'>{chip_html(verdict.transaction_ids[:8])}</div>",
                    unsafe_allow_html=True,
                )
            else:
                st.caption("Run a check above to see the verdict, confidence, and evidence here.")

    with history_col:
        with st.container(key="factcheck_history"):
            st.markdown("<div class='chart-heading'><div class='chart-title'>Session history</div>"
                        "<div class='chart-meta'>This run</div></div>", unsafe_allow_html=True)
            if not st.session_state.factcheck_history:
                st.caption("No claims checked yet this session.")
            else:
                badge_style = {
                    "supported": (GREEN, "rgba(53,208,127,.12)"),
                    "contradicted": (RED, "rgba(255,92,108,.12)"),
                    "partially_supported": ("#f5c451", "rgba(245,196,81,.12)"),
                    "unsupported": ("#f5c451", "rgba(245,196,81,.12)"),
                    "unverifiable": ("rgba(255,255,255,.55)", "rgba(255,255,255,.06)"),
                }
                for item in st.session_state.factcheck_history:
                    color, bg = badge_style.get(item["verdict"], (WHITE, "rgba(255,255,255,.06)"))
                    claim_short = html.escape(item["claim"][:70] + ("…" if len(item["claim"]) > 70 else ""))
                    st.markdown(
                        f"<div class='history-item'><span>•</span>"
                        f"<div><div class='claim'>{claim_short}</div>"
                        f"<div style='color:rgba(255,255,255,.35);font-size:.52rem;margin-top:.15rem'>{item['scope']}</div></div>"
                        f"<span class='badge' style='color:{color};background:{bg}'>{item['verdict'].replace('_',' ')}</span></div>",
                        unsafe_allow_html=True,
                    )
