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

# Apple system palette, light appearance.
INK = "#1D1D1F"
SECONDARY = "#6E6E73"
HAIRLINE = "rgba(0,0,0,.08)"
WHITE = "#FFFFFF"
BLUE = "#0071E3"
GREEN = "#34C759"
RED = "#FF3B30"
ORANGE = "#FF9500"
GRAY = "#D2D2D7"
FONT = "-apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Helvetica Neue', Helvetica, Arial, sans-serif"
HOVER = dict(bgcolor=WHITE, bordercolor=GRAY, font=dict(color=INK, family=FONT, size=12))

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
        margin=dict(l=8, r=12, t=30, b=24),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT, color=SECONDARY, size=11),
        hoverlabel=HOVER,
        legend=dict(
            orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
            font=dict(color=SECONDARY, size=11),
        ),
    )
    fig.update_xaxes(showgrid=False, zeroline=False, automargin=True, linecolor=HAIRLINE, tickfont=dict(color=SECONDARY))
    fig.update_yaxes(gridcolor="rgba(0,0,0,.06)", zeroline=False, automargin=True, tickfont=dict(color=SECONDARY))
    return fig


def donut_layout(fig: go.Figure, legend_x: float, legend_size: int = 11) -> go.Figure:
    fig.update_layout(
        height=275, margin=dict(l=2, r=2, t=8, b=8),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT, color=SECONDARY, size=11),
        legend=dict(x=legend_x, y=.5, xanchor="left", yanchor="middle", font=dict(color=SECONDARY, size=legend_size), bgcolor="rgba(0,0,0,0)"),
        hoverlabel=HOVER,
    )
    return fig


def revenue_quality_chart(monthly: pd.DataFrame) -> go.Figure:
    fig = chart_base()
    fig.add_trace(
        go.Scatter(
            x=monthly["period"], y=monthly["total_mrr"], name="Total MRR",
            mode="lines", line=dict(color=BLUE, width=2.5, shape="spline"),
            fill="tozeroy", fillcolor="rgba(0,113,227,.08)",
            hovertemplate="<b>%{x|%b %Y}</b><br>Total MRR $%{y:,.0f}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=monthly["period"], y=monthly["underlying_mrr"], name="Excluding largest account",
            mode="lines", line=dict(color="#86868B", width=2, dash="dot", shape="spline"),
            hovertemplate="<b>%{x|%b %Y}</b><br>Ex-largest $%{y:,.0f}<extra></extra>",
        )
    )
    fig.update_xaxes(tickformat="%b", dtick="M2")
    fig.update_yaxes(tickprefix="$", tickformat="~s")
    return fig


def concentration_chart(current: pd.DataFrame) -> go.Figure:
    ranked = current.sort_values("mrr", ascending=False).reset_index(drop=True)
    total_mrr = float(ranked["mrr"].sum())
    top_share = float(ranked.iloc[0]["mrr"]) / total_mrr if total_mrr else 0
    signal_color = RED if top_share >= .25 else GREEN
    visible_count = 8
    display = ranked.head(visible_count)[["customer", "mrr"]].copy()
    remaining_count = max(len(ranked) - visible_count, 0)
    display.loc[len(display)] = [f"Other {remaining_count:,} accounts", float(ranked.iloc[visible_count:]["mrr"].sum())]
    # The whale in red; everyone else on a quiet blue ramp, remainder in gray.
    colors = [signal_color, "#0071E3", "#3A8EEA", "#5EA3EE", "#82B8F2", "#A5CDF6", "#C2DDF9", "#DCEBFB", GRAY]
    fig = go.Figure(go.Pie(
        labels=display["customer"], values=display["mrr"], hole=.68, sort=False, direction="clockwise",
        marker=dict(colors=colors, line=dict(color=WHITE, width=2)),
        textinfo="none",
        hovertemplate="<b>%{label}</b><br>MRR $%{value:,.0f}<br>%{percent}<extra></extra>",
        domain=dict(x=[0, .57], y=[0, 1]),
    ))
    fig.add_annotation(
        x=.232, y=.5, xref="paper", yref="paper", showarrow=False,
        text=f"<b>{top_share:.0%}</b><br><span style='font-size:11px;color:{SECONDARY}'>Top account</span>",
        font=dict(color=INK, size=24, family=FONT),
    )
    return donut_layout(fig, legend_x=.62)


def bridge_chart(opening: float, expansion: float, losses: float, closing: float) -> go.Figure:
    fig = chart_base()
    fig.add_trace(
        go.Waterfall(
            x=["Opening", "Expansion", "Losses", "Closing"],
            y=[opening, expansion, losses, closing],
            measure=["absolute", "relative", "relative", "total"],
            connector=dict(line=dict(color=GRAY, width=1, dash="dot")),
            increasing=dict(marker=dict(color=GREEN)),
            decreasing=dict(marker=dict(color=RED)),
            totals=dict(marker=dict(color=BLUE)),
            text=[money(opening, True), money(expansion, True, True), money(losses, True, True), money(closing, True)],
            textposition="outside", textfont=dict(color=INK, size=11),
            hovertemplate="<b>%{x}</b><br>%{text}<extra></extra>",
        )
    )
    fig.update_yaxes(tickprefix="$", tickformat="~s")
    fig.update_layout(showlegend=False)
    return fig


def regime_state_chart(current: pd.DataFrame) -> go.Figure:
    labels = ["Growth", "Stable", "Decline"]
    state_counts = current["regime_state"].fillna("unknown").str.lower().value_counts()
    values = [int(state_counts.get(label.lower(), 0)) for label in labels]
    total = sum(values)
    fig = go.Figure(go.Pie(
        labels=labels, values=values, hole=.68, sort=False, direction="clockwise",
        marker=dict(colors=[GREEN, BLUE, RED], line=dict(color=WHITE, width=2)),
        textinfo="none",
        hovertemplate="<b>%{label}</b><br>%{value:,.0f} accounts<br>%{percent:.1%}<extra></extra>",
        domain=dict(x=[0, .57], y=[0, 1]),
    ))
    fig.add_annotation(
        x=.232, y=.5, xref="paper", yref="paper", showarrow=False,
        text=f"<b>{total:,}</b><br><span style='font-size:11px;color:{SECONDARY}'>accounts</span>",
        font=dict(color=INK, size=24, family=FONT),
    )
    return donut_layout(fig, legend_x=.62, legend_size=12)


def industry_distribution_chart(current: pd.DataFrame) -> go.Figure:
    industry_counts = current["industry"].fillna("Unknown").value_counts().sort_values(ascending=True)
    fig = chart_base()
    fig.add_trace(go.Bar(
        x=industry_counts.values, y=industry_counts.index, orientation="h",
        marker=dict(color=BLUE, cornerradius=4),
        hovertemplate="<b>%{y}</b><br>%{x:,.0f} accounts<extra></extra>",
    ))
    fig.update_layout(showlegend=False, bargap=.38, margin=dict(l=8, r=12, t=12, b=20))
    fig.update_xaxes(showgrid=True, gridcolor="rgba(0,0,0,.06)", nticks=6)
    fig.update_yaxes(showgrid=False)
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
    for status, color in [("Growing", BLUE), ("Declining / churned", RED)]:
        subset = merged[merged["status"].eq(status)]
        fig.add_trace(
            go.Scatter(
                x=subset["previous_mrr"], y=subset["growth"], name=status,
                mode="markers", text=subset["customer"],
                marker=dict(
                    color=color,
                    size=(subset["current_mrr"].clip(lower=10).pow(.5) * 1.2).clip(lower=6, upper=22),
                    line=dict(color=WHITE, width=1), opacity=.75,
                ),
                hovertemplate="<b>%{text}</b><br>Prior MRR $%{x:,.0f}<br>Growth %{y:+.1%}<extra></extra>",
            )
        )
    fig.add_hline(y=0, line_color=GRAY, line_width=1)
    fig.update_xaxes(title="Prior MRR", title_font=dict(size=11), tickprefix="$", tickformat="~s")
    fig.update_yaxes(title="Growth", title_font=dict(size=11), tickformat="+.0%")
    return fig


def risk_donut(top_share: float, is_risk: bool) -> go.Figure:
    indicator_color = RED if is_risk else GREEN
    fig = go.Figure(
        go.Pie(
            values=[top_share, 1 - top_share], labels=["Top customer", "All others"],
            hole=.76, sort=False, direction="clockwise",
            marker=dict(colors=[indicator_color, GRAY], line=dict(color=WHITE, width=3)),
            textinfo="none", hovertemplate="<b>%{label}</b><br>%{percent}<extra></extra>",
        )
    )
    fig.add_annotation(
        text=f"<b>{top_share:.0%}</b><br><span style='font-size:10px'>Top account</span>",
        x=.5, y=.5, showarrow=False, font=dict(color=INK, size=20, family=FONT),
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
    financial consequences (orange) -> accounts (blue, sized by MRR)."""
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
            node_color.append(ORANGE); node_size.append(18)
        else:
            node_color.append(BLUE); node_size.append(10)
        node_text.append(node)

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=edge_x, y=edge_y, mode="lines",
                              line=dict(color="rgba(0,0,0,.10)", width=1), hoverinfo="none"))
    fig.add_trace(go.Scatter(
        x=node_x, y=node_y, mode="markers", text=node_text, hovertemplate="<b>%{text}</b><extra></extra>",
        marker=dict(color=node_color, size=node_size, line=dict(color=WHITE, width=1.5)),
    ))
    fig.update_layout(
        showlegend=False, height=420, margin=dict(l=4, r=4, t=4, b=4),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", hoverlabel=HOVER,
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
        return f"{verdict.verdict.replace('_', ' ').capitalize()}. {verdict.reasoning}"

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
    :root {
      --bg:#F5F5F7; --card:#FFFFFF; --ink:#1D1D1F; --secondary:#6E6E73; --tertiary:#86868B;
      --hairline:rgba(0,0,0,.08); --fill:rgba(118,118,128,.12);
      --blue:#0071E3; --green:#248A3D; --red:#D70015; --orange:#C93400;
      --shadow:0 1px 2px rgba(0,0,0,.04),0 6px 20px rgba(0,0,0,.05);
      --radius:18px;
    }
    * { box-sizing:border-box; }
    html, body, .stApp, .stApp *:not([data-testid="stIconMaterial"]):not(svg *) {
      font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text","SF Pro Display","Helvetica Neue",Helvetica,Arial,sans-serif!important;
      -webkit-font-smoothing:antialiased;
    }
    /* Streamlit gives markdown blocks a -1rem bottom margin; cancel it for card-like blocks. */
    .metric-card,.kpi-strip,.section-line,.graph-legend,.evidence-chip-row:last-child { margin-bottom:1rem; }
    .stApp { color:var(--ink); background:var(--bg); }
    header[data-testid="stHeader"] { background:transparent; height:0; }
    #MainMenu,footer,[data-testid="stToolbar"],[data-testid="stDecoration"] { display:none!important; }
    .block-container { max-width:1440px!important; padding:0 2rem 2.5rem!important; }
    [data-testid="stVerticalBlock"] { gap:.9rem; }
    [data-testid="stHorizontalBlock"] { align-items:stretch; gap:.9rem; }
    h1,h2,h3,p { color:var(--ink); }

    /* -- top bar: translucent, hairline divider -- */
    .topbar { position:sticky; top:0; z-index:10; height:64px; display:flex; align-items:center; justify-content:space-between;
      margin:0 -2rem; padding:0 2rem; background:rgba(245,245,247,.8); backdrop-filter:saturate(180%) blur(20px);
      -webkit-backdrop-filter:saturate(180%) blur(20px); border-bottom:1px solid var(--hairline); }
    .brand { display:flex; align-items:center; gap:.65rem; }
    .brand-logo { width:34px; height:34px; display:grid; place-items:center; overflow:hidden; border-radius:50%; }
    .brand-logo img { width:34px; height:34px; object-fit:contain; transform:scale(1.72); }
    .brand-name { font-size:1.15rem; line-height:1; font-weight:600; letter-spacing:-.02em; color:var(--ink); }
    .brand-name span { color:var(--ink); }
    .tagline { margin-top:.2rem; color:var(--tertiary); font-size:.75rem; }
    .top-actions { display:flex; align-items:center; gap:.5rem; }
    .period-pill,.live-pill { padding:.35rem .75rem; border-radius:999px; background:var(--fill); color:var(--secondary); font-size:.75rem; font-weight:500; }
    .pulse { display:inline-block; width:6px; height:6px; margin-right:.4rem; border-radius:50%; background:#34C759; vertical-align:middle; }

    /* -- tabs as a segmented control -- */
    [data-testid="stTabs"] [role="tablist"] { gap:2px; width:fit-content; margin:1.2rem 0 .6rem; padding:2px; border:none; border-radius:9px; background:var(--fill); box-shadow:none; }
    [data-testid="stTabs"] [role="tablist"]::before,[data-testid="stTabs"] [role="tablist"]::after { display:none; }
    [data-testid="stTabs"] [role="tab"] { height:30px; padding:0 1.1rem; border:none; border-radius:7px; background:transparent; }
    [data-testid="stTabs"] [role="tab"] p { font-size:.82rem; font-weight:500; color:var(--ink); }
    [data-testid="stTabs"] [role="tab"][data-selected="true"] { background:var(--card); box-shadow:0 1px 3px rgba(0,0,0,.12),0 0 0 .5px rgba(0,0,0,.04); }
    [data-testid="stTabs"] .react-aria-SelectionIndicator { display:none; }

    /* -- section headers -- */
    .section-line { display:flex; align-items:end; justify-content:space-between; gap:2rem; padding-top:.6rem; }
    .eyebrow { color:var(--tertiary); font-size:.8rem; font-weight:500; }
    .section-title { margin:.15rem 0 0; color:var(--ink); font-size:1.75rem; font-weight:700; letter-spacing:-.025em; line-height:1.15; }
    .section-sub { max-width:520px; color:var(--tertiary); font-size:.78rem; line-height:1.45; text-align:right; }
    [data-testid="stSelectbox"] [role="group"] { min-height:38px; background:var(--card)!important; border:1px solid rgba(0,0,0,.12)!important; border-radius:10px!important; box-shadow:0 1px 2px rgba(0,0,0,.04); }
    [data-testid="stSelectbox"] input { color:var(--ink)!important; font-size:.88rem!important; }
    [data-testid="stWidgetLabel"] p { color:var(--secondary)!important; font-size:.78rem!important; font-weight:500!important; }

    /* -- KPI cards -- */
    .metric-card { height:112px; padding:1rem 1.1rem; border-radius:var(--radius); background:var(--card); box-shadow:var(--shadow); }
    .metric-head { display:flex; align-items:center; justify-content:space-between; color:var(--secondary); font-size:.78rem; font-weight:500; }
    .metric-head i { display:none; }
    .metric-value { margin:.45rem 0 .3rem; color:var(--ink); font-size:1.7rem; line-height:1; font-weight:600; letter-spacing:-.03em; font-variant-numeric:tabular-nums; }
    .metric-detail { color:var(--tertiary); font-size:.75rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
    .metric-detail b { font-weight:600; color:var(--ink); }
    .metric-card.positive .metric-detail b { color:var(--green); }
    .metric-card.risk .metric-detail b { color:var(--red); }

    /* -- cards -- */
    .st-key-chart_panel,.st-key-chart_panel_2,.st-key-chart_panel_3,.st-key-chart_panel_4,.st-key-chart_panel_5,.st-key-chart_panel_6,
    .st-key-agent_panel,.st-key-chart_panel_risk_amp,.st-key-chart_panel_risk_net,.st-key-chart_panel_risk_story,
    .st-key-chart_panel_risk_table,.st-key-chart_panel_risk_trace,.st-key-factcheck_input,.st-key-factcheck_history,.st-key-apikey_panel {
      border-radius:var(--radius); background:var(--card); box-shadow:var(--shadow); overflow:hidden; padding:1.1rem 1.2rem .7rem;
    }
    .chart-heading { display:flex; justify-content:space-between; align-items:center; gap:1rem; }
    .chart-title { color:var(--ink); font-size:.95rem; font-weight:600; letter-spacing:-.01em; }
    .chart-meta { color:var(--tertiary); font-size:.75rem; }
    .chart-meta.risk,.chart-meta.positive { padding:.2rem .6rem; border-radius:999px; font-weight:500; }
    .chart-meta.risk { color:var(--red); background:rgba(255,59,48,.10); }
    .chart-meta.positive { color:var(--green); background:rgba(52,199,89,.12); }
    div[data-testid="stPlotlyChart"] { background:transparent!important; }

    /* -- executive readout -- */
    .executive-strip { padding:1.1rem 1.2rem; border-radius:var(--radius); background:var(--card); box-shadow:var(--shadow); }
    .executive-strip-head { display:flex; justify-content:space-between; align-items:center; margin-bottom:.8rem; }
    .executive-strip-title { color:var(--ink); font-size:.95rem; font-weight:600; }
    .executive-strip-meta { color:var(--tertiary); font-size:.75rem; }
    .inference-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:1.2rem; }
    .inference-grid .story-step { padding:0; border-top:none; }

    .story-step { display:grid; grid-template-columns:24px 1fr; gap:.6rem; padding:.7rem 0; border-top:1px solid var(--hairline); }
    .story-step:first-of-type { border-top:none; }
    .story-step i { width:22px; height:22px; display:grid; place-items:center; color:var(--secondary); background:var(--fill); border-radius:50%; font-size:.7rem; font-style:normal; font-weight:600; }
    .story-step.risk i { color:#fff; background:#FF3B30; }
    .story-step.positive i { color:#fff; background:#34C759; }
    .story-label { color:var(--secondary); font-size:.75rem; font-weight:500; }
    .story-text { margin-top:.15rem; color:var(--ink); font-size:.82rem; line-height:1.45; }
    .story-text b { font-weight:600; color:var(--ink); }

    /* -- agent panel -- */
    .st-key-agent_panel { min-height:calc(100vh - 200px); padding:1.2rem; }
    .st-key-agent_panel>div[data-testid="stVerticalBlock"] { min-height:calc(100vh - 230px); }
    .chat-welcome { min-height:300px; display:flex; flex-direction:column; align-items:center; justify-content:center; text-align:center; }
    .chat-welcome-logo { width:72px; height:72px; display:grid; place-items:center; overflow:hidden; border-radius:50%; }
    .chat-welcome-logo img { width:72px; height:72px; object-fit:contain; transform:scale(1.68); }
    .chat-welcome strong { margin-top:.9rem; color:var(--ink); font-size:1.15rem; font-weight:600; letter-spacing:-.01em; }
    .chat-welcome span { max-width:280px; margin-top:.35rem; color:var(--tertiary); font-size:.82rem; line-height:1.5; }
    .chat-history { max-height:440px; padding:.3rem .1rem; overflow-y:auto; scrollbar-width:thin; }
    .chat-role { display:none; }
    .message-user,.message-agent { padding:.6rem .85rem; font-size:.85rem; line-height:1.45; border-radius:18px; }
    .message-user { margin:.5rem 0 .3rem 18%; color:#fff; background:var(--blue); border-bottom-right-radius:6px; }
    .message-agent { margin:.3rem 10% .3rem 0; color:var(--ink); background:#E9E9EB; border-bottom-left-radius:6px; }
    .st-key-agent_panel [data-testid="stForm"] { border:0; padding:0; margin-top:auto; }
    [data-testid="stCaptionContainer"] { color:var(--tertiary); font-size:.72rem; }

    /* -- inputs & buttons -- */
    div[data-testid="stTextInputRootElement"], div[data-testid="stTextAreaRootElement"] {
      background:var(--card)!important; border:1px solid var(--hairline)!important; border-radius:10px!important;
    }
    div[data-testid="stTextInputRootElement"]:focus-within, div[data-testid="stTextAreaRootElement"]:focus-within { border-color:var(--blue)!important; box-shadow:0 0 0 3px rgba(0,113,227,.18); }
    input[data-testid="stTextInputField"], textarea[data-testid="stTextAreaField"] { color:var(--ink)!important; background:transparent!important; border:none!important; font-size:.88rem!important; }
    input[data-testid="stTextInputField"]::placeholder, textarea[data-testid="stTextAreaField"]::placeholder { color:var(--tertiary)!important; }
    button[kind="secondary"], button[kind="secondaryFormSubmit"] { color:var(--blue)!important; background:var(--fill)!important; border:none!important; border-radius:980px!important; font-weight:500!important; }
    button[kind="secondary"]:hover, button[kind="secondaryFormSubmit"]:hover { background:rgba(0,113,227,.12)!important; }
    button[kind="secondary"] p, button[kind="secondaryFormSubmit"] p { color:inherit!important; font-size:.82rem!important; }
    button[kind="primary"], .st-key-agent_panel button[kind="secondaryFormSubmit"] { color:#fff!important; background:var(--blue)!important; border:none!important; border-radius:980px!important; font-weight:500!important; }
    button[kind="primary"]:hover, .st-key-agent_panel button[kind="secondaryFormSubmit"]:hover { background:#0077ED!important; }
    button[kind="primary"] p { color:#fff!important; }

    /* -- API key row -- */
    .st-key-apikey_panel { padding:.8rem 1.2rem; }
    .apikey-row { display:flex; align-items:center; gap:.7rem; }
    .apikey-label { color:var(--secondary); font-size:.78rem; font-weight:500; white-space:nowrap; }
    .llm-status { display:inline-flex; align-items:center; gap:.4rem; font-size:.75rem; font-weight:500; padding:.3rem .7rem; border-radius:999px; white-space:nowrap; }
    .llm-status.on { color:var(--green); background:rgba(52,199,89,.12); }
    .llm-status.off { color:var(--secondary); background:var(--fill); }
    .llm-status .dot { width:6px; height:6px; border-radius:50%; background:currentColor; }

    /* -- KPI strip (Risk Graph tab) -- */
    .kpi-strip { display:grid; grid-template-columns:repeat(4,1fr); gap:.9rem; }
    .kpi-tile { padding:1rem 1.1rem; border-radius:var(--radius); background:var(--card); box-shadow:var(--shadow); }
    .kpi-tile .kpi-label { color:var(--secondary); font-size:.78rem; font-weight:500; }
    .kpi-tile .kpi-value { margin-top:.4rem; font-size:1.5rem; font-weight:600; color:var(--ink); letter-spacing:-.025em; }
    .kpi-tile .kpi-sub { margin-top:.2rem; font-size:.75rem; color:var(--tertiary); }
    .kpi-tile.crit .kpi-value { color:var(--red); }

    /* -- severity pills + risk table -- */
    .sev-pill { display:inline-flex; align-items:center; padding:.18rem .6rem; border-radius:999px; font-size:.72rem; font-weight:500; }
    .sev-pill.critical { color:var(--red); background:rgba(255,59,48,.10); }
    .sev-pill.elevated { color:var(--orange); background:rgba(255,149,0,.12); }
    .sev-pill.normal { color:var(--secondary); background:var(--fill); }
    .risk-row { display:grid; grid-template-columns:1.1fr .9fr 1.3fr .9fr; align-items:center; gap:.5rem; padding:.6rem .1rem; border-top:1px solid var(--hairline); font-size:.85rem; }
    .risk-row.head { color:var(--tertiary); font-size:.75rem; font-weight:500; border-top:none; padding-bottom:.3rem; }
    .risk-row .acct { font-weight:600; color:var(--ink); }
    .risk-row .score { font-variant-numeric:tabular-nums; color:var(--ink); }
    .risk-row .driver { color:var(--secondary); }

    .risk-story-head { display:flex; justify-content:space-between; align-items:baseline; margin-bottom:.2rem; }
    .risk-story-head .t { font-size:.95rem; font-weight:600; color:var(--ink); }
    .risk-story-head .s { font-size:.75rem; color:var(--tertiary); }

    /* -- fact-check verdict -- */
    .verdict-hero { display:grid; grid-template-columns:auto 1fr; gap:1rem; align-items:center; padding:1rem 1.1rem; border-radius:14px; margin:.8rem 0; background:#F5F5F7; }
    .verdict-hero .icon { width:40px; height:40px; display:grid; place-items:center; border-radius:50%; color:#fff; font-size:1.1rem; font-weight:700; background:#8E8E93; }
    .verdict-hero.supported .icon { background:#34C759; }
    .verdict-hero.contradicted .icon { background:#FF3B30; }
    .verdict-hero.partially_supported .icon,.verdict-hero.unsupported .icon { background:#FF9500; }
    .verdict-hero .label { font-size:1.1rem; font-weight:600; letter-spacing:-.01em; color:var(--ink); }
    .verdict-hero .reason { margin-top:.25rem; font-size:.85rem; color:var(--secondary); line-height:1.5; }

    .meter { height:6px; border-radius:99px; background:var(--fill); overflow:hidden; margin-top:.5rem; }
    .meter i { display:block; height:100%; border-radius:99px; background:var(--blue); }
    .meter-label { display:flex; justify-content:space-between; font-size:.75rem; color:var(--tertiary); margin-top:.35rem; }
    .field-label { margin-top:.9rem; font-size:.75rem; font-weight:500; color:var(--secondary); }

    .evidence-chip-row { display:flex; flex-wrap:wrap; gap:.35rem; margin-top:.35rem; }
    .evidence-chip { font-family:"SF Mono",ui-monospace,Menlo,monospace!important; font-size:.72rem; padding:.2rem .55rem; border-radius:6px; background:var(--fill); color:var(--ink); }

    .history-item { display:grid; grid-template-columns:1fr auto; gap:.75rem; align-items:start; padding:.7rem 0; border-top:1px solid var(--hairline); font-size:.82rem; }
    .history-item:first-child { border-top:none; }
    .history-item .claim { color:var(--ink); }
    .history-item .scope { color:var(--tertiary); font-size:.72rem; margin-top:.15rem; }
    .history-item .badge { font-size:.72rem; font-weight:500; padding:.15rem .55rem; border-radius:999px; white-space:nowrap; text-transform:capitalize; }

    .loader-card { min-height:72vh; display:flex; flex-direction:column; align-items:center; justify-content:center; text-align:center; }
    .loader-card img { width:72px; height:72px; object-fit:contain; transform:scale(1.65); }
    .loader-card strong { margin-top:1rem; color:var(--ink); font-size:1.05rem; font-weight:600; }
    .loader-card span { margin-top:.3rem; color:var(--tertiary); font-size:.82rem; }
    .loader-line { width:160px; height:3px; margin-top:1.1rem; overflow:hidden; border-radius:99px; background:var(--fill); }
    .loader-line i { display:block; width:40%; height:100%; border-radius:99px; background:var(--blue); animation:loader-scan 1.2s ease-in-out infinite; }
    @keyframes loader-scan { from { transform:translateX(-110%); } to { transform:translateX(260%); } }

    @media(max-width:900px) {
      .block-container { padding:0 1rem 1.5rem!important; }
      .topbar { margin:0 -1rem; padding:0 1rem; }
      .tagline,.period-pill,.section-sub { display:none; }
      .section-title { font-size:1.35rem; }
      [data-testid="stHorizontalBlock"] { flex-wrap:wrap; }
      [data-testid="stHorizontalBlock"]>[data-testid="stColumn"] { min-width:calc(50% - .5rem); }
      .inference-grid,.kpi-strip { grid-template-columns:repeat(2,minmax(0,1fr)); }
      .st-key-agent_panel,.st-key-agent_panel>div[data-testid="stVerticalBlock"] { min-height:auto; }
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
    "<strong>Loading portfolio</strong>"
    "<span>Aggregating accounts and measuring concentration…</span>"
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

# Fail visibly if the CFO headline and account-level source ever stop reconciling.
account_total = float(current["mrr"].sum())
if abs(account_total - current_total) > max(.01, current_total * 1e-6):
    st.error("Account-level MRR does not reconcile to the monthly portfolio total.")
    st.stop()

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
      <div class="top-actions"><div class="period-pill">{period_label}</div>
      <div class="live-pill"><span class="pulse"></span>Updated {datetime.now().strftime('%-I:%M %p')}</div></div>
    </div>
    """,
    unsafe_allow_html=True,
)

tab_overview, tab_risk, tab_check = st.tabs(["Overview", "Risk Graph", "Fact-Check"])

with tab_overview:
    with st.container(key="apikey_panel"):
        key_col, status_col = st.columns([5, 1.4])
        with key_col:
            st.markdown("<div class='apikey-row'><span class='apikey-label'>Anthropic API key</span></div>", unsafe_allow_html=True)
            entered_key = st.text_input(
                "Anthropic API key", type="password", label_visibility="collapsed",
                value=st.session_state.get("anthropic_api_key", ""),
                placeholder="sk-ant-…  Optional. Leave blank to use template explanations.",
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
                f"<div style='padding-top:1.45rem;text-align:right'><span class='llm-status {'on' if llm_on else 'off'}'>"
                f"<span class='dot'></span>{'LLM connected' if llm_on else 'Template mode'}</span></div>",
                unsafe_allow_html=True,
            )

    title_col, selector_col = st.columns([5, 1.35])
    with title_col:
        st.markdown(
            f"<div class='section-line'><div><div class='eyebrow'>Revenue quality & concentration · {customer_count:,} accounts</div>"
            "<div class='section-title'>Growth is good. Durable growth is better.</div></div>"
            "</div>",
            unsafe_allow_html=True,
        )
    with selector_col:
        st.selectbox("Reporting period", [period_label], label_visibility="collapsed")

    k1, k2, k3, k4, k5, k6 = st.columns(6)
    with k1:
        st.markdown(metric_card("Total MRR", money(current_total, True), f"<b>{percentage(growth, True)}</b> vs last month", "$", "positive" if growth >= 0 else "risk"), unsafe_allow_html=True)
    with k2:
        st.markdown(metric_card("MRR excluding largest", money(organic_current, True), f"<b>{percentage(organic_growth, True)}</b> underlying growth", "↘", "positive" if organic_growth >= 0 else "risk"), unsafe_allow_html=True)
    with k3:
        st.markdown(metric_card("Largest account share", percentage(top_share), f"<b>{money(whale_mrr, True)}</b> from {whale}", "!", "risk" if concentration_risk else "positive"), unsafe_allow_html=True)
    with k4:
        concentration_label = "High" if top_five_share >= .50 else "Diversified"
        concentration_state = "risk" if top_five_share >= .50 else "positive"
        st.markdown(metric_card("Top 5 share", percentage(top_five_share), f"<b>{concentration_label}</b> portfolio dependency", "5", concentration_state), unsafe_allow_html=True)
    with k5:
        st.markdown(metric_card("Gross MRR loss", money(abs(losses), True), f"<b>{churned}</b> full-account churns", "−", "risk" if losses < 0 else "positive"), unsafe_allow_html=True)
    with k6:
        hhi_label = "Concentrated" if hhi > .18 else "Diversified"
        st.markdown(metric_card("HHI", f"{hhi * 10_000:,.0f}", f"<b>{hhi_label}</b> revenue base", "H", "risk" if hhi > .18 else "positive"), unsafe_allow_html=True)

    charts_col, agent_col = st.columns([2, 1], gap="medium")
    with charts_col:
        top_left, top_right = st.columns([1.25, 1])
        with top_left:
            with st.container(key="chart_panel"):
                st.markdown("<div class='chart-heading'><div class='chart-title'>Revenue quality</div><div class='chart-meta'>Total vs. excluding largest</div></div>", unsafe_allow_html=True)
                st.plotly_chart(revenue_quality_chart(monthly), width="stretch", config={"displayModeBar": False})
        with top_right:
            with st.container(key="chart_panel_2"):
                st.markdown(
                    f"<div class='chart-heading'><div class='chart-title'>Customer concentration</div>"
                    f"<div class='chart-meta {'risk' if concentration_risk else 'positive'}'>{risk_level}</div></div>",
                    unsafe_allow_html=True,
                )
                st.plotly_chart(concentration_chart(current), width="stretch", config={"displayModeBar": False})

        mid_left, mid_right = st.columns(2)
        with mid_left:
            with st.container(key="chart_panel_3"):
                st.markdown("<div class='chart-heading'><div class='chart-title'>MRR movement bridge</div><div class='chart-meta'>Month over month</div></div>", unsafe_allow_html=True)
                st.plotly_chart(bridge_chart(previous_total, expansion, losses, current_total), width="stretch", config={"displayModeBar": False})
        with mid_right:
            with st.container(key="chart_panel_4"):
                st.markdown("<div class='chart-heading'><div class='chart-title'>Company regime state</div><div class='chart-meta'>Latest portfolio</div></div>", unsafe_allow_html=True)
                st.plotly_chart(regime_state_chart(current), width="stretch", config={"displayModeBar": False})

        bottom_left, bottom_right = st.columns(2)
        with bottom_left:
            with st.container(key="chart_panel_5"):
                st.markdown("<div class='chart-heading'><div class='chart-title'>Industry distribution</div><div class='chart-meta'>Latest portfolio</div></div>", unsafe_allow_html=True)
                st.plotly_chart(industry_distribution_chart(current), width="stretch", config={"displayModeBar": False})
        with bottom_right:
            with st.container(key="chart_panel_6"):
                st.markdown("<div class='chart-heading'><div class='chart-title'>Customer growth map</div><div class='chart-meta'>Size × momentum</div></div>", unsafe_allow_html=True)
                st.plotly_chart(account_health_chart(current), width="stretch", config={"displayModeBar": False})

        st.markdown(
            "<div class='executive-strip'><div class='executive-strip-head'>"
            "<div class='executive-strip-title'>Executive concentration readout</div>"
            "<div class='executive-strip-meta'>Verified against latest account records</div></div>"
            f"<div class='inference-grid'>"
            f"<div class='story-step positive'><i>1</i><div><div class='story-label'>Baseline</div>"
            f"<div class='story-text'>MRR reached <b>{money(current_total, True)}</b>, up <b>{percentage(growth, True)}</b> month over month.</div></div></div>"
            f"<div class='story-step {story_class}'><i>2</i><div><div class='story-label'>Largest account</div>"
            f"<div class='story-text'><b>{html.escape(whale)}</b> moved {money(whale_mrr - previous_whale, True, True)} and now represents <b>{top_share:.1%}</b> of MRR.</div></div></div>"
            f"<div class='story-step risk'><i>3</i><div><div class='story-label'>Hidden losses</div>"
            f"<div class='story-text'><b>{money(abs(losses), True)} gross negative movement</b> across the portfolio; {churned} full-account churns.</div></div></div>"
            f"<div class='story-step {story_class}'><i>4</i><div><div class='story-label'>The real story</div>"
            f"<div class='story-text'><b>{real_story}</b></div></div></div>"
            f"</div></div>",
            unsafe_allow_html=True,
        )

    with agent_col:
        with st.container(key="agent_panel"):

            if "agent_messages" not in st.session_state:
                st.session_state.agent_messages = []
            messages = st.session_state.agent_messages

            if not messages:
                st.markdown(
                    f"<div class='chat-welcome'><div class='chat-welcome-logo'>"
                    f"<img src='{image_data_uri(LOGO_PATH)}' alt='WhaleWatch logo'></div>"
                    "<strong>Ask Mr. Whale</strong>"
                    "<span>Ask about concentration, the largest account, hidden losses, "
                    "revenue growth, or fact-check a claim (e.g. \"was growth broad-based?\").</span></div>",
                    unsafe_allow_html=True,
                )
            else:
                bubbles = []
                for message in messages[-8:]:
                    is_user = message["role"] == "user"
                    css_class = "message-user" if is_user else "message-agent"
                    role_label = "YOU" if is_user else "WHALE AGENT"
                    bubbles.append(
                        f"<div class='{css_class}'><div class='chat-role'>{role_label}</div>"
                        f"{html.escape(message['content'])}</div>"
                    )
                st.markdown("<div class='chat-history'>" + "".join(bubbles) + "</div>", unsafe_allow_html=True)

            with st.form("agent_form", clear_on_submit=True):
                question = st.text_input("Ask the agent", placeholder="Ask what makes growth fragile…", label_visibility="collapsed")
                submitted = st.form_submit_button("Ask", use_container_width=True)
            if submitted and question.strip():
                st.session_state.agent_messages.append({"role": "user", "content": question.strip()})
                answer = agent_answer(question, stats, engine, memory, current_period, comparison_period)
                st.session_state.agent_messages.append({"role": "agent", "content": answer})
                st.rerun()
            st.caption("Answers are grounded in account-level data.")



with tab_risk:
    st.markdown(
        "<div class='section-line'><div><div class='eyebrow'>Systemic risk graph</div>"
        "<div class='section-title'>Which accounts sit downstream of the most operational risk?</div></div>"
        "<div class='section-sub'>Reliability incidents, support friction and payment delays &rarr; financial "
        "consequences &rarr; accounts, ranked by weighted PageRank.</div></div>",
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
            amp_colors = [RED, ORANGE, BLUE]
            amp_fig.add_trace(go.Bar(
                x=[v for _, v in amplifier_ranking], y=[n.replace("_", " ") for n, _ in amplifier_ranking],
                orientation="h", marker=dict(color=amp_colors[:len(amplifier_ranking)], cornerradius=4),
                text=[money(v, True) for _, v in amplifier_ranking], textposition="outside",
                textfont=dict(color=INK, size=11),
                hovertemplate="<b>%{y}</b><br>$%{x:,.0f}<extra></extra>",
            ))
            amp_fig.update_xaxes(tickprefix="$", tickformat="~s")
            amp_fig.update_layout(height=170, margin=dict(l=8, r=64, t=6, b=20), bargap=.35)
            amp_fig.update_xaxes(range=[0, max(v for _, v in amplifier_ranking) * 1.22])
            st.plotly_chart(amp_fig, width="stretch", config={"displayModeBar": False})
    with net_col:
        with st.container(key="chart_panel_risk_net"):
            st.markdown("<div class='chart-heading'><div class='chart-title'>Risk flow graph</div>"
                        "<div class='chart-meta'>Risk source &rarr; consequence &rarr; account</div></div>", unsafe_allow_html=True)
            st.plotly_chart(risk_network_chart(graph_data), width="stretch", config={"displayModeBar": False})
            st.markdown(
                "<div class='chart-meta graph-legend'>"
                f"<span style='color:{RED}'>●</span> Operational risk source &nbsp;&nbsp; "
                f"<span style='color:{ORANGE}'>●</span> Financial consequence &nbsp;&nbsp; "
                f"<span style='color:{BLUE}'>●</span> Account</div>",
                unsafe_allow_html=True,
            )

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
                st.markdown(f"<div style='margin:.35rem 0'>{chips} &nbsp; <span class='chart-meta'>weight {path['total_weight']:,.2f}</span></div>", unsafe_allow_html=True)
        else:
            st.caption("No traceable operational-risk path to this account.")


with tab_check:
    st.markdown(
        "<div class='section-line'><div><div class='eyebrow'>Narrative fact-check</div>"
        "<div class='section-title'>Does the story match the transactions?</div></div>"
        "<div class='section-sub'>Paste a line from an earnings call, investor update, or exec summary. "
        "The verdict is computed from driver data, never from the LLM's own judgment.</div></div>",
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

            st.markdown("<div class='field-label'>Try an example, or write your own</div>",
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
            run_check = st.button("Check claim", type="primary", use_container_width=True)

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
                    "supported": ("✓", "Supported", "supported"),
                    "contradicted": ("✕", "Contradicted", "contradicted"),
                    "partially_supported": ("!", "Partially supported", "partially_supported"),
                    "unsupported": ("!", "Unsupported", "unsupported"),
                    "unverifiable": ("?", "Unverifiable", "unverifiable"),
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
                    "<div class='field-label'>Evidence</div>",
                    unsafe_allow_html=True,
                )
                chip_html = lambda items: "".join(f"<span class='evidence-chip'>{html.escape(str(i))}</span>" for i in items) or "<span class='evidence-chip'>none</span>"
                st.markdown(
                    f"<div class='field-label'>Claim named</div>"
                    f"<div class='evidence-chip-row'>{chip_html(claimed)}</div>"
                    f"<div class='field-label'>Actual top drivers</div>"
                    f"<div class='evidence-chip-row'>{chip_html(verdict.actual_top_entities)}</div>"
                    f"<div class='field-label'>Transactions</div>"
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
                    "supported": ("#248A3D", "rgba(52,199,89,.12)"),
                    "contradicted": ("#D70015", "rgba(255,59,48,.10)"),
                    "partially_supported": ("#C93400", "rgba(255,149,0,.12)"),
                    "unsupported": ("#C93400", "rgba(255,149,0,.12)"),
                    "unverifiable": (SECONDARY, "rgba(118,118,128,.12)"),
                }
                for item in st.session_state.factcheck_history:
                    color, bg = badge_style.get(item["verdict"], (SECONDARY, "rgba(118,118,128,.12)"))
                    claim_short = html.escape(item["claim"][:70] + ("…" if len(item["claim"]) > 70 else ""))
                    st.markdown(
                        f"<div class='history-item'>"
                        f"<div><div class='claim'>{claim_short}</div>"
                        f"<div class='scope'>{item['scope']}</div></div>"
                        f"<span class='badge' style='color:{color};background:{bg}'>{item['verdict'].replace('_',' ')}</span></div>",
                        unsafe_allow_html=True,
                    )
