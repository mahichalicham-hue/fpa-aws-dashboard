import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
from components.theme import apply_theme
from utils.data_loader import (
    load_data, MONTHS, ACTUAL_MONTHS, AWS_CAP, AWS_GROWTH_ACCOUNTS,
    COLOR_ACTUAL, COLOR_FORECAST, COLOR_ALERT, COLOR_AWS,
)
from utils.forecast_engine import forecast_aws, aws_monthly_summary, build_aws_validation_summary

apply_theme()
st.markdown("<div style='padding-top: 3rem;'></div>", unsafe_allow_html=True)

roster, _, _, aws_raw = load_data()
aws_df = forecast_aws(aws_raw)

# Merge roster for SVP filter
aws_df = aws_df.merge(roster[["Employee ID", "Supervisor 3"]], on="Employee ID", how="left")

# --- Filters ---
# st.markdown("### Filters")
f1, f2 = st.columns(2)
svp_opts = ["All"] + sorted(aws_df["Supervisor 3"].dropna().unique().tolist())
with f1:
    sel_svp = st.selectbox("SVP Group", svp_opts, key="aws_svp")
emp_pool = aws_df if sel_svp == "All" else aws_df[aws_df["Supervisor 3"] == sel_svp]
emp_opts = sorted(emp_pool["Employee Name"].dropna().unique().tolist())
with f2:
    sel_emps = st.multiselect("Employees", emp_opts, default=[], key="aws_emps")

filtered = emp_pool if not sel_emps else emp_pool[emp_pool["Employee Name"].isin(sel_emps)]

aws_val = build_aws_validation_summary(filtered)

# --- KPI row ---
st.markdown("""
<style>
div[data-testid="stMetric"] {
    height: 140px;
}
</style>
""", unsafe_allow_html=True)

c1, c2, c3 = st.columns(3)
c1.metric("AWS Full Year Forecast", f"${aws_val['Total AWS Forecast']:,.0f}")
c2.metric("Annual Cap", f"${AWS_CAP:,.0f}")
c3.metric("Variance to Cap", f"${aws_val['Variance to Cap']:,.0f}",
          delta="Under" if not aws_val["Over Cap"] else "OVER",
          delta_color="normal" if not aws_val["Over Cap"] else "inverse")

# --- Cumulative spend vs cap ---
st.markdown("### Cumulative AWS Spend vs Cap")

aws_month = aws_monthly_summary(filtered)
aws_month["Cumulative"] = aws_month["AWS Cost"].cumsum()

fig_cum = go.Figure()
fig_cum.add_trace(go.Scatter(
    x=aws_month["Month"], y=aws_month["Cumulative"],
    mode="lines+markers", fill="tozeroy",
    line=dict(color=COLOR_AWS, width=2), fillcolor="rgba(214,158,46,0.15)",
    name="Cumulative Spend",
))
fig_cum.add_hline(y=AWS_CAP, line_dash="dash", line_color=COLOR_ALERT,
                  annotation_text=f"Cap: ${AWS_CAP:,.0f}", annotation_position="top left")
fig_cum.update_layout(
    xaxis=dict(categoryorder="array", categoryarray=MONTHS),
    yaxis_title="Cumulative Cost ($)", template="plotly_white", height=380,
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    margin=dict(l=60, r=20, t=20, b=40),
)
st.plotly_chart(fig_cum, use_container_width=True)

# --- Top 5 Account KPIs ---
st.markdown("### Top 5 Cost-Driving Accounts")
acct_totals = filtered.groupby(["Account Number", "Employee Name"], as_index=False)["Full Year Forecast"].sum()
acct_totals = acct_totals.nlargest(5, "Full Year Forecast")
total_all = filtered["Full Year Forecast"].sum()
acct_totals["% of Total"] = acct_totals["Full Year Forecast"] / total_all * 100 if total_all > 0 else 0
st.dataframe(
    acct_totals[["Account Number", "Employee Name", "Full Year Forecast", "% of Total"]].style.format(
        {"Full Year Forecast": "${:,.0f}", "% of Total": "{:.1f}%"}
    ),
    hide_index=True,
    use_container_width=True,
)

# # --- Cumulative spend vs cap ---
# st.markdown("### Cumulative AWS Spend vs Cap")

# aws_month = aws_monthly_summary(filtered)
# aws_month["Cumulative"] = aws_month["AWS Cost"].cumsum()

# fig_cum = go.Figure()
# fig_cum.add_trace(go.Scatter(
#     x=aws_month["Month"], y=aws_month["Cumulative"],
#     mode="lines+markers", fill="tozeroy",
#     line=dict(color=COLOR_AWS, width=2), fillcolor="rgba(214,158,46,0.15)",
#     name="Cumulative Spend",
# ))
# fig_cum.add_hline(y=AWS_CAP, line_dash="dash", line_color=COLOR_ALERT,
#                   annotation_text=f"Cap: ${AWS_CAP:,.0f}", annotation_position="top left")
# fig_cum.update_layout(
#     xaxis=dict(categoryorder="array", categoryarray=MONTHS),
#     yaxis_title="Cumulative Cost ($)", template="plotly_white", height=380,
#     paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
#     margin=dict(l=60, r=20, t=20, b=40),
# )
# st.plotly_chart(fig_cum, use_container_width=True)

# --- Account Trends + Stacked (side by side) ---
acct_long = filtered.melt(
    id_vars=["Account Number", "Employee Name"],
    value_vars=MONTHS, var_name="Month", value_name="Cost",
)
acct_long["Growth"] = acct_long["Account Number"].isin(AWS_GROWTH_ACCOUNTS)

col_left, col_right = st.columns(2)

with col_left:
    st.markdown("### Account Monthly Trends")
    fig_lines = px.line(
        acct_long, x="Month", y="Cost", color="Account Number",
        category_orders={"Month": MONTHS},
        line_dash="Growth", line_dash_map={True: "solid", False: "dot"},
        hover_data=["Employee Name"],
    )
    fig_lines.update_layout(template="plotly_white", height=300,
                            legend=dict(font=dict(size=8)),
                            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                            margin=dict(l=40, r=10, t=10, b=40))
    st.plotly_chart(fig_lines, use_container_width=True)

with col_right:
    st.markdown("### Monthly Cost by Account (Stacked)")
    fig_stack = px.bar(
        acct_long, x="Month", y="Cost", color="Account Number",
        category_orders={"Month": MONTHS},
        color_discrete_sequence=["#DD6B20", "#D69E2E", "#4A5568", "#2D3748", "#C53030",
                                 "#DD6B20", "#D69E2E", "#4A5568"],
    )
    fig_stack.update_layout(
        barmode="stack", template="plotly_white", height=300,
        legend=dict(font=dict(size=8)),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=40, r=10, t=10, b=40),
    )
    st.plotly_chart(fig_stack, use_container_width=True)

# --- Assumptions ---
st.markdown("### Forecast Assumptions")
st.markdown(f"""
- **Growth accounts** ({', '.join(AWS_GROWTH_ACCOUNTS)}): 5% month-over-month from March.
- **All other accounts**: Jan–Mar weighted average applied to Apr–Dec.
- Annual cap monitored at **${AWS_CAP:,.0f}**.
""")
