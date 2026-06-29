import streamlit as st
import plotly.graph_objects as go
from components.theme import apply_theme
from utils.data_loader import (
    load_data, MONTHS, ACTUAL_MONTHS, FORECAST_MONTHS, AWS_CAP,
    COLOR_ACTUAL, COLOR_FORECAST, COLOR_LABOR, COLOR_AWS, COLOR_ALERT,
)
from utils.forecast_engine import (
    forecast_labor, forecast_aws,
    labor_monthly_summary, aws_monthly_summary,
    labor_by_project_summary, build_aws_validation_summary,
)

apply_theme()
st.markdown("<div style='padding-top: 3rem;'></div>", unsafe_allow_html=True)

# Load and compute
roster, project, eta, aws_raw = load_data()
labor_df = forecast_labor(eta, roster, project)
aws_df = forecast_aws(aws_raw)

labor_month = labor_monthly_summary(labor_df)
aws_month = aws_monthly_summary(aws_df)
aws_val = build_aws_validation_summary(aws_df)

labor_costs = labor_month["Labor Cost"].tolist()
aws_costs = aws_month["AWS Cost"].tolist()

total_labor = sum(labor_costs)
total_aws = sum(aws_costs)
total_fy = total_labor + total_aws

avg_actual_labor = sum(labor_costs[:3]) / 3
avg_forecast_labor = sum(labor_costs[3:]) / 9
avg_actual_aws = sum(aws_costs[:3]) / 3
avg_forecast_aws = sum(aws_costs[3:]) / 9

delta_labor = avg_forecast_labor - avg_actual_labor
delta_aws = avg_forecast_aws - avg_actual_aws
delta_total = delta_labor + delta_aws

# --- KPI Row ---
c1, c2, c3, c4 = st.columns(4)
c1.metric("Full Year Forecast", f"${total_fy:,.0f}", delta=f"${delta_total:+,.0f}/mo vs actuals")
c2.metric("Labor Forecast", f"${total_labor:,.0f}", delta=f"${delta_labor:+,.0f}/mo vs actuals")
c3.metric("AWS Forecast", f"${total_aws:,.0f}", delta=f"${delta_aws:+,.0f}/mo vs actuals")
c4.metric("AWS Variance to Cap", f"${aws_val['Variance to Cap']:,.0f}",
          delta="Under" if not aws_val["Over Cap"] else "OVER CAP",
          delta_color="normal" if not aws_val["Over Cap"] else "inverse")

# --- Sparklines ---
def make_sparkline(values, title, color):
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=MONTHS[:3], y=values[:3], mode="lines+markers",
        line=dict(color=COLOR_ACTUAL, width=2), marker=dict(size=5),
        name="Actual",
    ))
    fig.add_trace(go.Scatter(
        x=MONTHS[2:], y=values[2:], mode="lines+markers",
        line=dict(color=color, width=2, dash="dot"), marker=dict(size=5),
        name="Forecast",
    ))
    y_min, y_max = min(values), max(values)
    padding = max((y_max - y_min) * 0.3, y_max * 0.05)
    fig.update_layout(
        height=220, margin=dict(l=50, r=10, t=30, b=60),
        xaxis=dict(tickmode="array", tickvals=MONTHS, title=""),
        yaxis=dict(tickformat=",", range=[y_min - padding, y_max + padding]),
        title=dict(text=title, font=dict(size=12, color="#4A5568")),
        legend=dict(orientation="h", yanchor="bottom", y=-0.55, xanchor="center", x=0.5, font=dict(size=9)),
        template="plotly_white",
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig

st.markdown("### Monthly Trends")
s1, s2 = st.columns(2)
s1.plotly_chart(make_sparkline(labor_costs, "Labor Cost ($)", COLOR_LABOR), use_container_width=True)
s2.plotly_chart(make_sparkline(aws_costs, "AWS Cost ($)", COLOR_AWS), use_container_width=True)

# --- Top 5 Cost Drivers ---
st.markdown("### Top 5 Project Cost Drivers")
proj_summary = labor_by_project_summary(labor_df)
top5 = proj_summary[["Project Number", "Project Name", "Full Year Cost"]].head(5).reset_index(drop=True)
top5["Full Year Cost"] = top5["Full Year Cost"].apply(lambda x: f"${x:,.0f}")
st.dataframe(top5, use_container_width=True, hide_index=True)

# --- Sankey ---
st.markdown("### Budget Flow — Funding BU → Project → Employee Type")

cost_cols = [f"{m}_Cost" for m in MONTHS]
labor_df["_fy_cost"] = labor_df[cost_cols].sum(axis=1)

flow = labor_df.groupby(["Funding Business Unit", "Project Name", "Type"], as_index=False)["_fy_cost"].sum()
flow = flow[flow["_fy_cost"] > 0]

top_projects = flow.groupby("Project Name")["_fy_cost"].sum().nlargest(10).index.tolist()
flow = flow[flow["Project Name"].isin(top_projects)]

fbus = flow["Funding Business Unit"].unique().tolist()
projects = flow["Project Name"].unique().tolist()
types = flow["Type"].unique().tolist()
nodes = fbus + projects + types

# Warm palette for FBUs
fbu_colors = ["#DD6B20", "#D69E2E", "#4A5568", "#2D3748", "#C53030", "#DD6B20", "#D69E2E", "#4A5568"]
fbu_color_map = {fbu: fbu_colors[i % len(fbu_colors)] for i, fbu in enumerate(fbus)}

sources, targets, values, link_colors = [], [], [], []
for _, row in flow.iterrows():
    sources.append(nodes.index(row["Funding Business Unit"]))
    targets.append(nodes.index(row["Project Name"]))
    values.append(row["_fy_cost"])
    link_colors.append(fbu_color_map[row["Funding Business Unit"]])

    sources.append(nodes.index(row["Project Name"]))
    targets.append(nodes.index(row["Type"]))
    values.append(row["_fy_cost"])
    link_colors.append(fbu_color_map[row["Funding Business Unit"]])

def hex_to_rgba(h, alpha=0.4):
    h = h.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"

link_colors = [hex_to_rgba(c) for c in link_colors]

fig_sankey = go.Figure(go.Sankey(
    node=dict(pad=20, thickness=20, label=nodes,
              color=[fbu_color_map.get(n, "#4A5568") for n in nodes]),
    link=dict(source=sources, target=targets, value=values, color=link_colors),
    textfont=dict(size=13, color="#000000", family="Arial Black"),
))
fig_sankey.update_layout(
    font=dict(size=13, color="#000000"), height=500,
    margin=dict(l=20, r=20, t=10, b=20),
    paper_bgcolor="#FFFAF0",
)
st.plotly_chart(fig_sankey, use_container_width=True)

labor_df.drop(columns=["_fy_cost"], inplace=True)
