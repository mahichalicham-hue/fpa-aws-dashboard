import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from components.theme import apply_theme
from components.filters import render_filters
from utils.data_loader import (
    load_data, MONTHS, ACTUAL_MONTHS, FORECAST_MONTHS,
    COLOR_ACTUAL, COLOR_FORECAST, COLOR_ALERT,
    ENDED_PROJECTS,
)
from utils.forecast_engine import forecast_labor, labor_monthly_summary

apply_theme()
st.markdown("<div style='padding-top: 3rem;'></div>", unsafe_allow_html=True)

roster, project, eta, aws_raw = load_data()
labor_df = forecast_labor(eta, roster, project)

# --- Pill filters (replaces sidebar) ---
filtered = render_filters(labor_df)

# Compute cost columns
cost_cols = [f"{m}_Cost" for m in MONTHS]
filtered["Full Year Cost"] = filtered[cost_cols].sum(axis=1)

# --- Cost and Usage Graph ---
st.markdown("### Cost and Usage Graph")
st.caption("Jan–Mar: Actuals  |  Apr–Dec: Forecasted")

labor_month = labor_monthly_summary(filtered)
actual_vals = labor_month[labor_month["Type"] == "Actual"]["Labor Cost"].values
forecast_vals = labor_month[labor_month["Type"] == "Forecast"]["Labor Cost"].values

total_cost = labor_month["Labor Cost"].sum()
avg_actual = actual_vals.mean() if len(actual_vals) > 0 else 0
avg_forecast = forecast_vals.mean() if len(forecast_vals) > 0 else 0

k1, k2, k3 = st.columns(3)
k1.metric("Total Cost (Historical & Forecasted)", f"${total_cost:,.0f}")
k2.metric("Avg Historical Cost / Month", f"${avg_actual:,.0f}")
k3.metric("Avg Forecasted Cost / Month", f"${avg_forecast:,.0f}")

costs = labor_month["Labor Cost"].values
types = labor_month["Type"].values

fig_cost = go.Figure()

actual_mask = [t == "Actual" for t in types]
fig_cost.add_trace(go.Bar(
    x=[MONTHS[i] for i, m in enumerate(actual_mask) if m],
    y=[costs[i] for i, m in enumerate(actual_mask) if m],
    name="Actuals", marker=dict(color=COLOR_ACTUAL),
))

forecast_mask = [t == "Forecast" for t in types]
fig_cost.add_trace(go.Bar(
    x=[MONTHS[i] for i, m in enumerate(forecast_mask) if m],
    y=[costs[i] for i, m in enumerate(forecast_mask) if m],
    name="Forecast",
    marker=dict(color="rgba(255,255,255,0)", line=dict(color=COLOR_FORECAST, width=2)),
))

# Prediction interval
forecast_x = [MONTHS[i] for i, m in enumerate(forecast_mask) if m]
forecast_y = [costs[i] for i, m in enumerate(forecast_mask) if m]
intervals = [0.05 + 0.015 * i for i in range(len(forecast_y))]
upper_err = [c * pct for c, pct in zip(forecast_y, intervals)]
lower_err = [c * pct for c, pct in zip(forecast_y, intervals)]

fig_cost.add_trace(go.Scatter(
    x=forecast_x, y=forecast_y, mode="markers",
    marker=dict(size=0.1, color="rgba(0,0,0,0)"),
    error_y=dict(type="data", symmetric=False, array=upper_err, arrayminus=lower_err,
                 color="#4A5568", thickness=1.5, width=6),
    name="80% Prediction Interval", showlegend=True,
))

fig_cost.add_vline(x="Sep", line_dash="dash", line_color=COLOR_ALERT, line_width=1)
fig_cost.add_annotation(x="Sep", y=max(costs) * 1.05, text="P10/P14 sunset",
                        showarrow=False, font=dict(size=10, color=COLOR_ALERT))

fig_cost.update_layout(
    xaxis=dict(categoryorder="array", categoryarray=MONTHS, title=""),
    yaxis=dict(title="Costs ($)", tickformat=","),
    template="plotly_white", height=420, barmode="group",
    legend=dict(orientation="h", yanchor="bottom", y=-0.2, xanchor="center", x=0.5),
    margin=dict(l=60, r=20, t=20, b=60),
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
)
st.plotly_chart(fig_cost, use_container_width=True)

# --- Gantt Chart ---
st.markdown("### Resource Gantt Chart")

month_to_date = {m: pd.Timestamp(f"2026-{i+1:02d}-01") for i, m in enumerate(MONTHS)}
gantt_rows = []
for (pnum, pname, fbu), grp in filtered.groupby(["Project Number", "Project Name", "Funding Business Unit"]):
    monthly_hrs = [grp[m].sum() for m in MONTHS]
    active = [i for i, h in enumerate(monthly_hrs) if h > 0]
    if active:
        start = month_to_date[MONTHS[active[0]]]
        end_month = min(active[-1], 7) if pnum in ENDED_PROJECTS else active[-1]
        end = month_to_date[MONTHS[end_month]] + pd.DateOffset(months=1)
        gantt_rows.append(dict(Project=pname, Start=start, End=end, FBU=fbu,
                               Ended="Yes" if pnum in ENDED_PROJECTS else "No"))

if gantt_rows:
    gantt_df = pd.DataFrame(gantt_rows)
    fig_gantt = px.timeline(gantt_df, x_start="Start", x_end="End", y="Project", color="FBU",
                            pattern_shape="Ended", pattern_shape_map={"Yes": "/", "No": ""})
    fig_gantt.update_layout(height=max(300, len(gantt_rows) * 28), template="plotly_white",
                            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                            margin=dict(l=10, r=10, t=10, b=80), showlegend=True,
                            legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5))
    st.plotly_chart(fig_gantt, use_container_width=True)

# --- Treemap ---
st.markdown("### Budget Composition — Treemap")

treemap_df = filtered[filtered["Full Year Cost"] > 0][
    ["Funding Business Unit", "Project Name", "Employee Name", "Full Year Cost"]
].copy()

fig_tree = px.treemap(
    treemap_df, path=["Funding Business Unit", "Project Name", "Employee Name"],
    values="Full Year Cost", color="Full Year Cost",
    color_continuous_scale=[[0, "#FFFAF0"], [0.5, "#DD6B20"], [1, "#2D3748"]],
)
fig_tree.update_layout(margin=dict(t=10, l=10, r=10, b=10), height=500,
                       paper_bgcolor="rgba(0,0,0,0)")
st.plotly_chart(fig_tree, use_container_width=True)




