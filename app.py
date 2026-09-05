from __future__ import annotations

import base64
import html
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st


ROOT = Path(__file__).resolve().parent
DATA_PATH = ROOT / "data" / "data.csv"
OUTPUT_PATH = ROOT / "data" / "output.csv"
CONCENTRATION_PATH = ROOT / "data" / "concentration_overrides.csv"
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
def load_real_data(
    path: Path,
    overrides_path: Path,
    overrides_version: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Stream the 1.2 GB CSV and retain only CFO aggregates and latest accounts."""
    import pyarrow as pa
    import pyarrow.csv as pacsv

    del overrides_version  # Included in the cache key so CSV edits invalidate aggregates.
    overrides = pd.read_csv(overrides_path)
    override_columns = [
        "current_mrr", "previous_mrr", "mrr_change", "positive_transaction_amount",
        "negative_transaction_amount", "expansion_amount", "churn_amount", "churn_flag",
    ]
    override_map = {
        (int(row["account_id"]), int(row["month"])): row
        for _, row in overrides.iterrows()
    }
    override_accounts = set(overrides["account_id"].astype(int))

    columns = [
        "account_id", "month", "company_size", "industry", "contract_type",
        "regime_state", "current_mrr", "previous_mrr", "mrr_change",
        "positive_transaction_amount", "negative_transaction_amount",
        "expansion_amount", "churn_amount", "churn_flag", "timestamp",
    ]
    reader = pacsv.open_csv(
        path,
        read_options=pacsv.ReadOptions(block_size=32 * 1024 * 1024, use_threads=True),
        convert_options=pacsv.ConvertOptions(
            include_columns=columns,
            column_types={
                "account_id": pa.int64(), "month": pa.int32(),
                "current_mrr": pa.float64(), "previous_mrr": pa.float64(),
                "mrr_change": pa.float64(), "positive_transaction_amount": pa.float64(),
                "negative_transaction_amount": pa.float64(), "expansion_amount": pa.float64(),
                "churn_amount": pa.float64(), "churn_flag": pa.bool_(),
            },
        ),
    )

    monthly_parts: list[pd.DataFrame] = []
    latest_parts: list[pd.DataFrame] = []
    latest_month = -1
    numeric = [
        "current_mrr", "previous_mrr", "mrr_change", "positive_transaction_amount",
        "negative_transaction_amount", "expansion_amount", "churn_amount",
    ]
    for batch in reader:
        chunk = batch.to_pandas()
        candidate_rows = chunk.index[chunk["account_id"].isin(override_accounts)]
        for row_index in candidate_rows:
            key = (int(chunk.at[row_index, "account_id"]), int(chunk.at[row_index, "month"]))
            override = override_map.get(key)
            if override is not None:
                for column in override_columns:
                    chunk.at[row_index, column] = override[column]
        chunk[numeric] = chunk[numeric].fillna(0)
        chunk["churn_flag"] = chunk["churn_flag"].fillna(False).astype(int)
        chunk["active_customer"] = chunk["current_mrr"].gt(0).astype(int)
        grouped = chunk.groupby("month", as_index=False).agg(
            total_mrr=("current_mrr", "sum"),
            previous_mrr=("previous_mrr", "sum"),
            net_change=("mrr_change", "sum"),
            expansion=("positive_transaction_amount", "sum"),
            losses=("negative_transaction_amount", "sum"),
            churn_mrr=("churn_amount", "sum"),
            churned=("churn_flag", "sum"),
            active_customers=("active_customer", "sum"),
            largest_account_mrr=("current_mrr", "max"),
            timestamp=("timestamp", "max"),
        )
        monthly_parts.append(grouped)

        batch_max = int(chunk["month"].max())
        if batch_max > latest_month:
            latest_month = batch_max
            latest_parts = []
        latest_slice = chunk[chunk["month"].eq(latest_month)].copy()
        if not latest_slice.empty:
            latest_parts.append(latest_slice)

    monthly = pd.concat(monthly_parts, ignore_index=True)
    monthly = monthly.groupby("month", as_index=False).agg(
        total_mrr=("total_mrr", "sum"), previous_mrr=("previous_mrr", "sum"),
        net_change=("net_change", "sum"), expansion=("expansion", "sum"),
        losses=("losses", "sum"), churn_mrr=("churn_mrr", "sum"),
        churned=("churned", "sum"), active_customers=("active_customers", "sum"),
        largest_account_mrr=("largest_account_mrr", "max"), timestamp=("timestamp", "max"),
    )
    monthly["period"] = pd.to_datetime(monthly["timestamp"], errors="coerce").dt.to_period("M").dt.to_timestamp()
    monthly["month_label"] = monthly["period"].dt.strftime("%b %Y")
    monthly["underlying_mrr"] = monthly["total_mrr"] - monthly["largest_account_mrr"]
    monthly = monthly.sort_values("month").reset_index(drop=True)

    latest = pd.concat(latest_parts, ignore_index=True)
    latest = latest[latest["month"].eq(latest_month)].drop_duplicates("account_id", keep="last")
    latest["customer"] = latest["account_id"].map(lambda value: f"Account {int(value):06d}")
    latest["mrr"] = latest["current_mrr"].clip(lower=0)
    return monthly, latest


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
    total_mrr = float(ranked["mrr"].sum())
    top_share = float(ranked.iloc[0]["mrr"]) / total_mrr if total_mrr else 0
    concentration_risk = top_share >= .25
    signal_color = RED if concentration_risk else GREEN
    visible_count = 8
    display = ranked.head(visible_count)[["customer", "mrr"]].copy()
    remaining_count = max(len(ranked) - visible_count, 0)
    display.loc[len(display)] = [
        f"Other {remaining_count:,} accounts",
        float(ranked.iloc[visible_count:]["mrr"].sum()),
    ]
    colors = [
        "#FF5C6C", "#184D87", "#3AC0EF", "#7C5CFC", "#F5A623",
        "#FF7EB6", "#00C2A8", "#FFD166", "#33A1DD",
    ]
    fig = go.Figure(
        go.Pie(
            labels=display["customer"],
            values=display["mrr"],
            hole=.58,
            sort=False,
            direction="clockwise",
            marker=dict(colors=colors, line=dict(color=BLACK, width=2)),
            pull=[.025] + [0] * (len(display) - 1),
            textinfo="none",
            hovertemplate="<b>%{label}</b><br>MRR $%{value:,.0f}<br>%{percent}<extra></extra>",
            domain=dict(x=[0, .57], y=[0, 1]),
        )
    )
    fig.add_annotation(
        x=.232, y=.5, xref="paper", yref="paper", showarrow=False,
        text=f"<b>{top_share:.0%}</b><br><span style='font-size:10px'>TOP 1%</span>",
        font=dict(color=signal_color, size=20),
    )
    fig.update_layout(
        height=275,
        margin=dict(l=2, r=2, t=8, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, Arial, sans-serif", color="rgba(255,255,255,.68)", size=9),
        legend=dict(
            x=.60, y=.5, xanchor="left", yanchor="middle",
            font=dict(color="rgba(255,255,255,.66)", size=8),
            bgcolor="rgba(0,0,0,0)", traceorder="normal",
        ),
        hoverlabel=dict(bgcolor=BLACK, bordercolor=TEAL, font_color=WHITE),
    )
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


def regime_state_chart(current: pd.DataFrame) -> go.Figure:
    labels = ["Growth", "Stable", "Decline"]
    state_counts = current["regime_state"].fillna("unknown").str.lower().value_counts()
    values = [int(state_counts.get(label.lower(), 0)) for label in labels]
    colors = [GREEN, LIGHT_BLUE, RED]
    total = sum(values)

    fig = go.Figure(
        go.Pie(
            labels=labels,
            values=values,
            sort=False,
            direction="clockwise",
            marker=dict(colors=colors, line=dict(color=BLACK, width=2)),
            texttemplate="<b>%{label}</b><br>%{percent:.1%}",
            textposition="inside",
            insidetextorientation="horizontal",
            textfont=dict(color=WHITE, size=11),
            hovertemplate="<b>%{label}</b><br>%{value:,.0f} companies<br>%{percent:.1%}<extra></extra>",
            domain=dict(x=[0, .72], y=[0, 1]),
        )
    )
    fig.update_layout(
        height=275,
        margin=dict(l=2, r=2, t=8, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, Arial, sans-serif", color="rgba(255,255,255,.68)", size=9),
        legend=dict(
            x=.76, y=.5, xanchor="left", yanchor="middle",
            font=dict(color="rgba(255,255,255,.66)", size=9),
            bgcolor="rgba(0,0,0,0)", traceorder="normal",
        ),
        hoverlabel=dict(bgcolor=BLACK, bordercolor=TEAL, font_color=WHITE),
        uniformtext_minsize=10,
        uniformtext_mode="hide",
    )
    fig.add_annotation(
        x=.76, y=.33, xref="paper", yref="paper", showarrow=False, xanchor="left",
        text=f"<span style='color:rgba(255,255,255,.40)'>{total:,} companies</span>",
        font=dict(size=9),
    )
    return fig


def industry_distribution_chart(current: pd.DataFrame) -> go.Figure:
    industry_counts = current["industry"].fillna("Unknown").value_counts().sort_values(ascending=False)
    colors = [
        "#00C2FF", "#7C5CFC", "#FFB020", "#FF5C6C", "#00C2A8",
        "#F15BB5", "#9BDE4F", "#FF8A4C", "#66A3FF", "#C8A2FF",
    ]
    fig = go.Figure(
        go.Pie(
            labels=industry_counts.index,
            values=industry_counts.values,
            sort=False,
            direction="clockwise",
            marker=dict(colors=colors[:len(industry_counts)], line=dict(color=BLACK, width=2)),
            textinfo="none",
            hovertemplate="<b>%{label}</b><br>%{value:,.0f} companies<br>%{percent:.1%}<extra></extra>",
            domain=dict(x=[0, .58], y=[0, 1]),
        )
    )
    fig.update_layout(
        height=275,
        margin=dict(l=0, r=0, t=8, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, Arial, sans-serif", color="rgba(255,255,255,.68)", size=8),
        legend=dict(
            x=.61, y=.5, xanchor="left", yanchor="middle",
            font=dict(color="rgba(255,255,255,.66)", size=7),
            bgcolor="rgba(0,0,0,0)", traceorder="normal",
        ),
        hoverlabel=dict(bgcolor=BLACK, bordercolor=TEAL, font_color=WHITE),
    )
    return fig


def agent_answer(question: str, stats: dict[str, object]) -> str:
    q = question.lower().strip()
    if any(word in q for word in ("whale", "concentration", "risk", "fragile")):
        return (
            f"{stats['whale']} contributes {stats['top_share']:.0%} of MRR. "
            f"Losing it would reduce monthly revenue by {money(float(stats['whale_mrr']), True)}."
        )
    if any(word in q for word in ("churn", "lost", "customer")):
        return (
            f"Gross negative movement was {money(abs(float(stats['losses'])), True)} across the portfolio. "
            f"The full-account churn count was {stats['churned']}."
        )
    if any(word in q for word in ("revenue", "growth", "baseline", "mrr")):
        return (
            f"Total MRR is {money(float(stats['current_total']), True)}, "
            f"{percentage(float(stats['growth']), True)} month over month. "
            f"Excluding the top customer, the portfolio moved {percentage(float(stats['organic_growth']), True)}."
        )
    if any(word in q for word in ("action", "recommend", "do", "next")):
        return (
            f"Protect {stats['whale']}'s renewal, investigate "
            f"{money(abs(float(stats['losses'])), True)} in gross negative movement, "
            "and reduce Top-1 exposure below 25%."
        )
    return "Ask about the whale, hidden churn, revenue quality, or the next CFO action."


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

    .st-key-chart_panel,.st-key-chart_panel_2,.st-key-chart_panel_3,.st-key-chart_panel_4,.st-key-chart_panel_5,.st-key-agent_panel { border:1px solid rgba(51,161,221,.18); border-radius:14px; background:linear-gradient(145deg,rgba(24,77,135,.14),rgba(0,0,0,.66)); box-shadow:0 16px 42px rgba(0,0,0,.34); overflow:hidden; }
    .st-key-chart_panel,.st-key-chart_panel_2,.st-key-chart_panel_3,.st-key-chart_panel_4,.st-key-chart_panel_5 { padding:.68rem .72rem .38rem; }
    .chart-heading { display:flex; justify-content:space-between; align-items:center; }
    .chart-title { color:var(--white); font-size:.75rem; font-weight:750; }
    .chart-meta { color:rgba(255,255,255,.34); font-size:.49rem; letter-spacing:.06em; text-transform:uppercase; }
    .chart-meta.risk { display:flex; align-items:center; gap:.34rem; padding:.3rem .5rem; color:var(--red); background:rgba(255,92,108,.12); border:1px solid rgba(255,92,108,.48); border-radius:999px; box-shadow:0 0 18px rgba(255,92,108,.20); font-size:.52rem; font-weight:900; letter-spacing:.09em; }
    .chart-meta.risk:before { content:""; width:6px; height:6px; flex:0 0 6px; border-radius:50%; background:var(--red); box-shadow:0 0 0 0 rgba(255,92,108,.55); animation:risk-pulse 1.8s ease-out infinite; }
    @keyframes risk-pulse { 70% { box-shadow:0 0 0 6px rgba(255,92,108,0); } 100% { box-shadow:0 0 0 0 rgba(255,92,108,0); } }
    .chart-meta.positive { color:var(--green); font-weight:850; }
    div[data-testid="stPlotlyChart"] { background:transparent!important; }

    .st-key-agent_panel { min-height:calc(100vh - 165px); padding:.75rem; border-color:rgba(58,192,239,.31); background:linear-gradient(165deg,rgba(24,77,135,.37),rgba(0,0,0,.91) 48%); }
    .st-key-agent_panel>div[data-testid="stVerticalBlock"] { min-height:calc(100vh - 190px); }
    .agent-head { display:flex; justify-content:space-between; align-items:start; padding-bottom:.55rem; border-bottom:1px solid rgba(255,255,255,.10); }
    .agent-title { color:var(--white); font-size:.82rem; font-weight:820; }
    .agent-sub { margin-top:.1rem; color:rgba(255,255,255,.42); font-size:.54rem; }
    .agent-badge { color:var(--teal); font-size:.48rem; font-weight:850; letter-spacing:.08em; }
    .chat-welcome { min-height:480px; display:flex; flex-direction:column; align-items:center; justify-content:center; text-align:center; }
    .chat-welcome-logo { width:170px; height:170px; display:grid; place-items:center; overflow:hidden; border-radius:50%; }
    .chat-welcome-logo img { width:170px; height:170px; object-fit:contain; transform:scale(1.68); filter:drop-shadow(0 0 30px rgba(58,192,239,.25)); animation:whale-float 2.4s ease-in-out infinite; }
    .chat-welcome strong { margin-top:.8rem; color:var(--white); font-size:1rem; }
    .chat-welcome span { max-width:290px; margin-top:.3rem; color:rgba(255,255,255,.45); font-size:.62rem; line-height:1.5; }
    .chat-history { min-height:480px; max-height:560px; padding:.7rem .15rem; overflow-y:auto; scrollbar-width:thin; scrollbar-color:var(--navy) transparent; }
    .chat-role { margin-bottom:.18rem; color:rgba(255,255,255,.38); font-size:.44rem; font-weight:850; letter-spacing:.09em; text-transform:uppercase; }
    .story-step { display:grid; grid-template-columns:22px 1fr; gap:.45rem; padding:.42rem 0; border-top:1px solid rgba(255,255,255,.08); }
    .story-step i { width:20px; height:20px; display:grid; place-items:center; color:var(--teal); background:rgba(58,192,239,.09); border:1px solid rgba(58,192,239,.17); border-radius:6px; font-size:.48rem; font-style:normal; font-weight:850; }
    .story-step.risk i { color:var(--red); border-color:rgba(255,92,108,.28); background:rgba(255,92,108,.08); }
    .story-step.positive i { color:var(--green); border-color:rgba(53,208,127,.25); background:rgba(53,208,127,.07); }
    .story-label { color:rgba(255,255,255,.42); font-size:.46rem; font-weight:850; letter-spacing:.1em; text-transform:uppercase; }
    .story-text { margin-top:.1rem; color:rgba(255,255,255,.73); font-size:.57rem; line-height:1.38; }
    .story-text b { color:var(--white); }
    .story-step.risk .story-text b { color:var(--red); }
    .story-step.positive .story-text b { color:var(--green); }
    .executive-strip { padding:.58rem .68rem .62rem; border:1px solid rgba(51,161,221,.18); border-radius:13px; background:linear-gradient(145deg,rgba(24,77,135,.14),rgba(0,0,0,.72)); box-shadow:0 14px 38px rgba(0,0,0,.30); }
    .executive-strip-head { display:flex; justify-content:space-between; align-items:center; margin-bottom:.4rem; }
    .executive-strip-title { color:var(--white); font-size:.68rem; font-weight:800; }
    .executive-strip-meta { color:var(--teal); font-size:.46rem; font-weight:800; letter-spacing:.09em; text-transform:uppercase; }
    .inference-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:.4rem; }
    .inference-grid .story-step { min-height:58px; padding:.42rem; border:1px solid rgba(255,255,255,.08); border-radius:9px; background:rgba(255,255,255,.025); }
    .inference-grid .story-label { font-size:.43rem; }
    .inference-grid .story-text { font-size:.52rem; line-height:1.32; }
    .message-user,.message-agent { padding:.62rem .7rem; font-size:.62rem; line-height:1.48; border:1px solid rgba(255,255,255,.09); }
    .message-user { margin:.5rem 0 .38rem 18%; color:var(--white); background:var(--blue); border-radius:11px 11px 3px 11px; }
    .message-agent { margin:.38rem 10% .38rem 0; color:rgba(255,255,255,.78); background:rgba(255,255,255,.055); border-radius:11px 11px 11px 3px; }
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

    @media(max-width:900px) {
      .block-container { padding:.6rem!important; }
      .tagline { display:none; }
      [data-testid="stHorizontalBlock"] { flex-wrap:wrap; }
      [data-testid="stHorizontalBlock"]>[data-testid="stColumn"] { min-width:calc(50% - .5rem); }
      .inference-grid { grid-template-columns:1fr 1fr; }
      .st-key-agent_panel { min-height:auto; }
      .st-key-agent_panel>div[data-testid="stVerticalBlock"] { min-height:auto; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


if not OUTPUT_PATH.exists() or not CONCENTRATION_PATH.exists():
    st.error("Required input data was not found in the data directory.")
    st.stop()

loader = st.empty()
loader.markdown(
    f"<div class='loader-card'><img src='{image_data_uri(LOGO_PATH)}' alt='WhaleWatch loading'>"
    "<strong>WhaleWatch is scanning your revenue ocean</strong>"
    "<span>Aggregating 1.15 million records, identifying whales, and measuring hidden churn…</span>"
    "<div class='loader-line'><i></i></div></div>",
    unsafe_allow_html=True,
)
monthly, current = load_real_data(
    OUTPUT_PATH,
    CONCENTRATION_PATH,
    CONCENTRATION_PATH.stat().st_mtime_ns,
)
loader.empty()
if monthly.empty or current.empty:
    st.error("data/output.csv did not contain usable monthly account records.")
    st.stop()

latest_month = monthly.iloc[-1]
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
concentration_risk = top_share >= .25
risk_level = "High concentration risk" if concentration_risk else "Low concentration risk"
story_class = "risk" if concentration_risk else "positive"
real_story = (
    f"Revenue is fragile: one non-renewal removes {money(whale_mrr, True)} in MRR."
    if concentration_risk
    else f"Revenue is diversified across {customer_count:,} accounts; churn is the larger near-term risk."
)
story_markup = (
    f"<div class='story-step positive'><i>1</i><div><div class='story-label'>Baseline</div>"
    f"<div class='story-text'>MRR reached <b>{money(current_total, True)}</b>, up <b>{percentage(growth, True)}</b> month over month.</div></div></div>"
    f"<div class='story-step {story_class}'><i>2</i><div><div class='story-label'>Largest account</div>"
    f"<div class='story-text'><b>{html.escape(whale)}</b> moved {money(whale_mrr - previous_whale, True, True)} and now represents <b>{top_share:.1%}</b> of MRR.</div></div></div>"
    f"<div class='story-step risk'><i>3</i><div><div class='story-label'>Hidden losses</div>"
    f"<div class='story-text'><b>{money(abs(losses), True)} gross negative movement</b> across the portfolio; {churned} full-account churns.</div></div></div>"
    f"<div class='story-step {story_class}'><i>4</i><div><div class='story-label'>The real story</div>"
    f"<div class='story-text'><b>{real_story}</b></div></div></div>"
)

# Fail visibly if the CFO headline and account-level source ever stop reconciling.
account_total = float(current["mrr"].sum())
if abs(account_total - current_total) > max(.01, current_total * 1e-10):
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
    </div>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    "<div class='section-line'><div><div class='eyebrow'>Revenue quality & concentration</div>"
    f"<div class='section-sub'>Portfolio view · {customer_count:,} accounts · Source: data/output.csv</div></div>",
    unsafe_allow_html=True,
)

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
            st.markdown(
                f"<div class='chart-heading'><div class='chart-title'>Customer concentration</div>"
                f"<div class='chart-meta {'risk' if concentration_risk else 'positive'}'>{risk_level}</div></div>",
                unsafe_allow_html=True,
            )
            st.plotly_chart(concentration_chart(current), width="stretch", config={"displayModeBar": False})

    bottom_left, bottom_middle, bottom_right = st.columns(3)
    with bottom_left:
        with st.container(key="chart_panel_3"):
            st.markdown("<div class='chart-heading'><div class='chart-title'>MRR movement bridge</div><div class='chart-meta'>Month over month</div></div>", unsafe_allow_html=True)
            st.plotly_chart(bridge_chart(previous_total, expansion, losses, current_total), width="stretch", config={"displayModeBar": False})
    with bottom_middle:
        with st.container(key="chart_panel_4"):
            st.markdown("<div class='chart-heading'><div class='chart-title'>Company regime state</div><div class='chart-meta'>Latest portfolio</div></div>", unsafe_allow_html=True)
            st.plotly_chart(regime_state_chart(current), width="stretch", config={"displayModeBar": False})
    with bottom_right:
        with st.container(key="chart_panel_5"):
            st.markdown("<div class='chart-heading'><div class='chart-title'>Industry distribution</div><div class='chart-meta'>Latest portfolio</div></div>", unsafe_allow_html=True)
            st.plotly_chart(industry_distribution_chart(current), width="stretch", config={"displayModeBar": False})

    st.markdown(
        "<div class='executive-strip'><div class='executive-strip-head'>"
        "<div class='executive-strip-title'>Executive concentration readout</div>"
        "<div class='executive-strip-meta'>Verified against latest account records</div></div>"
        f"<div class='inference-grid'>{story_markup}</div></div>",
        unsafe_allow_html=True,
    )

with agent_col:
    with st.container(key="agent_panel"):
        st.markdown(
            "<div class='agent-head'><div><div class='agent-title'>Whale Agent</div>"
            "<div class='agent-sub'>Ask your revenue data</div></div>"
            "<div class='agent-badge'>● ONLINE</div></div>", unsafe_allow_html=True,
        )
        if "whale_chat_messages_v2" not in st.session_state:
            st.session_state.whale_chat_messages_v2 = []

        messages = st.session_state.whale_chat_messages_v2
        if not messages:
            st.markdown(
                f"<div class='chat-welcome'><div class='chat-welcome-logo'>"
                f"<img src='{image_data_uri(LOGO_PATH)}' alt='WhaleWatch logo'></div>"
                "<strong>Ask Mr. Whale</strong>"
                "<span>Ask about concentration, the largest account, hidden losses, "
                "revenue growth, or the next CFO action.</span></div>",
                unsafe_allow_html=True,
            )
        else:
            chat_bubbles = []
            for message in messages[-8:]:
                is_user = message["role"] == "user"
                css_class = "message-user" if is_user else "message-agent"
                role_label = "YOU" if is_user else "WHALE AGENT"
                chat_bubbles.append(
                    f"<div class='{css_class}'><div class='chat-role'>{role_label}</div>"
                    f"{html.escape(message['content'])}</div>"
                )
            st.markdown(
                "<div class='chat-history'>" + "".join(chat_bubbles) + "</div>",
                unsafe_allow_html=True,
            )

        with st.form("agent_form", clear_on_submit=True):
            question = st.text_input("Ask the agent", placeholder="Ask about revenue concentration…", label_visibility="collapsed")
            submitted = st.form_submit_button("Ask Whale Agent", use_container_width=True)
        if submitted and question.strip():
            st.session_state.whale_chat_messages_v2.append({"role": "user", "content": question.strip()})
            st.session_state.whale_chat_messages_v2.append({"role": "agent", "content": agent_answer(question, stats)})
            st.rerun()
        st.caption("Answers calculated from data/output.csv")
