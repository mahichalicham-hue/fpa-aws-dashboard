import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from components.theme import apply_theme
from utils.data_loader import (
    load_data, MONTHS, FORECAST_MONTHS, ACTUAL_MONTHS,
    COLOR_ACTUAL, COLOR_FORECAST,
)
from utils.forecast_engine import forecast_labor

apply_theme()
st.markdown("<div style='padding-top: 3rem;'></div>", unsafe_allow_html=True)

roster, project, eta, aws_raw = load_data()
labor_df = forecast_labor(eta, roster, project)

# --- Group Filters ---
# st.markdown("### Employee Filter")
f1, f2 = st.columns(2)
svp_opts = ["All"] + sorted(labor_df["Supervisor 3"].dropna().unique().tolist())
type_opts = ["All"] + sorted(labor_df["Type"].dropna().unique().tolist())
with f1:
    sel_svp = st.selectbox("SVP Group", svp_opts, key="sp_svp")
with f2:
    sel_type = st.selectbox("Employee Type", type_opts, key="sp_type")

pool = labor_df.copy()
if sel_svp != "All":
    pool = pool[pool["Supervisor 3"] == sel_svp]
if sel_type != "All":
    pool = pool[pool["Type"] == sel_type]

emp_list = sorted(pool["Employee Name"].dropna().unique().tolist())

# --- Tabbed KPI / Histogram per employee ---
if emp_list:
    tabs = st.tabs(emp_list)
    cost_cols = [f"{m}_Cost" for m in MONTHS]
    for tab, emp_name in zip(tabs, emp_list):
        with tab:
            emp_data = pool[pool["Employee Name"] == emp_name]
            rate = emp_data["Hourly Rate"].iloc[0]
            emp_type = emp_data["Type"].iloc[0]
            monthly_costs = [emp_data[f"{m}_Cost"].sum() for m in MONTHS]
            fy_cost = sum(monthly_costs)
            avg_hrs = emp_data[MONTHS].sum(axis=1).mean()
            top_proj_cost = emp_data.groupby("Project Name")[cost_cols].sum().sum(axis=1)
            top_proj_pct = (top_proj_cost.max() / fy_cost * 100) if fy_cost > 0 else 0

            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Full Year Cost", f"${fy_cost:,.0f}")
            k2.metric("Avg Hrs/Project", f"{avg_hrs:.0f}")
            k3.metric("Hourly Rate", f"${rate:.0f}/hr")
            k4.metric("Top Project %", f"{top_proj_pct:.0f}%")

            # Cost histogram
            colors = [COLOR_ACTUAL if m in ACTUAL_MONTHS else COLOR_FORECAST for m in MONTHS]
            fig = go.Figure(go.Bar(x=MONTHS, y=monthly_costs, marker_color=colors))
            fig.update_layout(height=280, template="plotly_white", yaxis_title="Cost ($)",
                              margin=dict(l=50, r=10, t=10, b=30),
                              paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig, use_container_width=True, key=f"sp_hist_{emp_name}")
else:
    st.info("No employees match the selected filters.")

# --- Existing Scenario Planner functionality below ---
st.markdown("---")
st.markdown("## What-If Analysis")
whatif_action = st.radio("Select scenario type:",
    ["Transfer Employee", "Project Sunset", "Employee Layoff"],
    horizontal=True, key="whatif_action")

all_employees = sorted(labor_df["Employee Name"].dropna().unique().tolist())
all_projects = sorted(labor_df["Project Name"].dropna().unique().tolist())
cost_cols = [f"{m}_Cost" for m in MONTHS]

if whatif_action == "Transfer Employee":
    wi1, wi2 = st.columns(2)
    with wi1:
        tf_emp = st.selectbox("Employee", all_employees, key="tf_emp")
    emp_rows = labor_df[labor_df["Employee Name"] == tf_emp]
    emp_projects = sorted(emp_rows["Project Name"].unique().tolist())
    with wi2:
        tf_source = st.selectbox("Source Project", emp_projects, key="tf_src")

    wi3, wi4 = st.columns(2)
    dest_options = [p for p in all_projects if p != tf_source]
    with wi3:
        tf_dest = st.selectbox("Destination Project", dest_options, key="tf_dst")
    with wi4:
        tf_months = st.multiselect("Months", FORECAST_MONTHS, default=FORECAST_MONTHS, key="tf_months")

    tf_mode = st.radio("Transfer mode:", ["Partial (specify hours)", "Full Transfer"], horizontal=True, key="tf_mode")
    tf_hours = 0.0
    if tf_mode == "Partial (specify hours)":
        tf_hours = st.number_input("Hours per month to transfer", min_value=0.0, step=5.0, value=20.0, key="tf_hrs")

    if tf_months:
        rate = emp_rows["Hourly Rate"].iloc[0]
        source_row = emp_rows[emp_rows["Project Name"] == tf_source]
        dest_row = emp_rows[emp_rows["Project Name"] == tf_dest]

        results = []
        for m in tf_months:
            src_before = source_row[m].sum() if not source_row.empty else 0
            dst_before = dest_row[m].sum() if not dest_row.empty else 0
            moved = src_before if tf_mode == "Full Transfer" else min(tf_hours, src_before)
            results.append({"Month": m, "Source Before": src_before, "Source After": src_before - moved,
                           "Dest Before": dst_before, "Dest After": dst_before + moved, "Hrs Moved": moved})

        result_df = pd.DataFrame(results)
        st.dataframe(result_df.style.format({c: "{:.1f}" for c in result_df.columns if c != "Month"}),
                     use_container_width=True, hide_index=True)

        total_moved = result_df["Hrs Moved"].sum()
        cost_impact = total_moved * rate
        st.metric("Total Hours Transferred", f"{total_moved:.0f} hrs")
        st.markdown(
            f'<div style="background:#FDF6EC;border:1.5px solid #C4C9D2;border-radius:0.5rem;padding:1rem 1.25rem;margin-top:0.5rem;">'
            f'<span style="font-size:1.3rem;font-weight:700;color:#2D3748;">'
            f'Cost Redistribution: <span style="color:#DD6B20;">${cost_impact:,.0f}</span></span><br>'
            f'<span style="font-size:1.05rem;color:#4A5568;">'
            f'{tf_source} → {tf_dest} &nbsp;·&nbsp; Net budget impact: <strong>$0</strong></span></div>',
            unsafe_allow_html=True,
        )

        # Constraint check
        emp_total_hrs = emp_rows[FORECAST_MONTHS].sum().to_dict()
        violations = [m for m in tf_months if result_df.loc[result_df["Month"] == m, "Source After"].iloc[0] < 0]
        if violations:
            st.warning(f"⚠ Source project hours go negative in: {', '.join(violations)}. Reduce transfer amount.")

elif whatif_action == "Project Sunset":
    ws1, ws2 = st.columns(2)
    with ws1:
        sunset_proj = st.selectbox("Project to Sunset", all_projects, key="ws_proj")
    with ws2:
        sunset_month = st.selectbox("Last Active Month", FORECAST_MONTHS, key="ws_month")

    sunset_idx = FORECAST_MONTHS.index(sunset_month)
    affected_months = FORECAST_MONTHS[sunset_idx + 1:]

    if affected_months:
        affected_emps = labor_df[labor_df["Project Name"] == sunset_proj].copy()

        if affected_emps.empty:
            st.info("No employees are assigned to this project.")
        else:
            st.markdown(f"**Affected employees:** {len(affected_emps)} — Hours zeroed from {affected_months[0]} onward")
            redistribution = []

            for _, emp_row in affected_emps.iterrows():
                emp_id = emp_row["Employee ID"]
                emp_name = emp_row["Employee Name"]
                rate = emp_row["Hourly Rate"]
                # Get all projects for this employee except the sunset project and PTO
                other_rows = labor_df[(labor_df["Employee ID"] == emp_id) &
                                     (labor_df["Project Name"] != sunset_proj) &
                                     (labor_df["Project Number"] != "P00015")]
                freed_total = sum(emp_row[m] for m in affected_months)
                cost_freed = freed_total * rate

                if other_rows.empty:
                    target = "Meetings (default)"
                else:
                    weights = other_rows[affected_months].sum(axis=1)
                    top_proj = other_rows.loc[weights.idxmax(), "Project Name"] if weights.sum() > 0 else "Meetings"
                    target = top_proj

                redistribution.append({"Employee": emp_name, "Hours Freed": freed_total,
                                      "Cost Freed": cost_freed, "Redistributed To": target})

            redist_df = pd.DataFrame(redistribution)
            st.dataframe(redist_df.style.format({"Hours Freed": "{:.0f}", "Cost Freed": "${:,.0f}"}),
                         use_container_width=True, hide_index=True)

            total_hrs_freed = redist_df["Hours Freed"].sum()
            st.metric("Total Hours Redistributed", f"{total_hrs_freed:.0f} hrs")
            st.caption("Net cost impact: $0 (hours move to other projects at same employee rates)")
    else:
        st.info("Select a month before December to see sunset impact.")

elif whatif_action == "Employee Layoff":
    wl1, wl2 = st.columns(2)
    with wl1:
        layoff_emp = st.selectbox("Employee", all_employees, key="wl_emp")
    with wl2:
        layoff_month = st.selectbox("Effective Month", FORECAST_MONTHS, key="wl_month")

    layoff_mode = st.radio("View mode:", ["Cost Savings", "Redistribute Hours"], horizontal=True, key="wl_mode")

    layoff_idx = FORECAST_MONTHS.index(layoff_month)
    affected_months = FORECAST_MONTHS[layoff_idx:]
    emp_rows = labor_df[labor_df["Employee Name"] == layoff_emp]
    rate = emp_rows["Hourly Rate"].iloc[0]

    if layoff_mode == "Cost Savings":
        monthly_savings = []
        for m in affected_months:
            hrs = emp_rows[m].sum()
            monthly_savings.append({"Month": m, "Hours Saved": hrs, "Cost Saved": hrs * rate})
        savings_df = pd.DataFrame(monthly_savings)
        st.dataframe(savings_df.style.format({"Hours Saved": "{:.0f}", "Cost Saved": "${:,.0f}"}),
                     use_container_width=True, hide_index=True)
        total_saved = savings_df["Cost Saved"].sum()
        st.metric("Total Cost Savings", f"${total_saved:,.0f}",
                  delta=f"-{sum(savings_df['Hours Saved']):.0f} hrs removed")
    else:
        # Redistribute: for each project, spread hours to other employees on same project
        redist_rows = []
        for _, proj_row in emp_rows.iterrows():
            proj_name = proj_row["Project Name"]
            proj_hrs = sum(proj_row[m] for m in affected_months)
            if proj_hrs <= 0:
                continue
            # Find other employees on same project
            others = labor_df[(labor_df["Project Name"] == proj_name) &
                             (labor_df["Employee Name"] != layoff_emp)]
            if others.empty:
                redist_rows.append({"Project": proj_name, "Hours": proj_hrs,
                                   "Receiving Employee": "(unassigned)", "Hrs Added/Month": proj_hrs / len(affected_months),
                                   "Constraint Risk": "⚠ No other employees"})
            else:
                per_person = proj_hrs / len(others) / len(affected_months)
                for _, other_row in others.iterrows():
                    curr_monthly = sum(other_row[m] for m in affected_months) / len(affected_months)
                    new_monthly = curr_monthly + per_person
                    risk = "⚠ Over 160" if new_monthly > 160 else "✓ OK"
                    redist_rows.append({"Project": proj_name, "Hours": proj_hrs / len(others),
                                       "Receiving Employee": other_row["Employee Name"],
                                       "Hrs Added/Month": per_person, "Constraint Risk": risk})

        if redist_rows:
            redist_df = pd.DataFrame(redist_rows)
            st.dataframe(redist_df.style.format({"Hours": "{:.0f}", "Hrs Added/Month": "{:.1f}"}),
                         use_container_width=True, hide_index=True)
            total_hrs = sum(r["Hours"] for r in redist_rows)
            violations = [r for r in redist_rows if "Over 160" in r["Constraint Risk"]]
            if violations:
                st.warning(f"⚠ {len(violations)} employee(s) would exceed 160 hrs/month capacity.")
            st.metric("Total Hours Redistributed", f"{total_hrs:.0f} hrs",
                      delta=f"across {len(set(r['Receiving Employee'] for r in redist_rows if r['Receiving Employee'] != '(unassigned)'))} employees")
        else:
            st.info("This employee has no forecast hours in the selected period.")

# --- What-If session state for scenario save ---
if "whatif_results" not in st.session_state:
    st.session_state["whatif_results"] = {}
st.session_state["whatif_results"] = {"action": whatif_action}

st.markdown("---")
st.markdown("## Individual Employee Scenario Editor")

emp_options = sorted(labor_df["Employee Name"].dropna().unique().tolist())
selected_emp = st.selectbox("Select Employee", emp_options, key="sp_emp")

emp_data = labor_df[labor_df["Employee Name"] == selected_emp].copy()
emp_rate = emp_data["Hourly Rate"].iloc[0]
emp_type = emp_data["Type"].iloc[0]

st.caption(f"**{selected_emp}** — {emp_type} — ${emp_rate:.0f}/hr")

# --- Editable grid ---
edit_df = emp_data[["Project Number", "Project Name"] + FORECAST_MONTHS].copy()
edit_df = edit_df.set_index(["Project Number", "Project Name"])

baseline_key = f"bl_{selected_emp}"
if baseline_key not in st.session_state:
    st.session_state[baseline_key] = edit_df.copy()

if st.button("Reset to Baseline", key="sp_reset"):
    st.session_state.pop(f"edited_{selected_emp}", None)
    st.rerun()

st.markdown("### Monthly Hour Allocations (Apr–Dec)")
edited = st.data_editor(
    edit_df.reset_index(), disabled=["Project Number", "Project Name"],
    num_rows="fixed", key=f"edited_{selected_emp}", use_container_width=True,
)

# --- Validation ---
st.markdown("### Validation")
month_totals = edited[FORECAST_MONTHS].sum()
violations = month_totals[abs(month_totals - 160) > 0.01]

if violations.empty:
    st.markdown("""<div style="border-left: 4px solid #38A169; background: #FDF6EC;
        padding: 0.75rem 1rem; border-radius: 0.25rem; color: #2D3748;">
        ✓ All months sum to 160 hours.</div>""", unsafe_allow_html=True)
else:
    violation_text = "<br>".join(f"• {m}: {val:.1f} hrs (expected 160)" for m, val in violations.items())
    st.markdown(f"""<div style="border-left: 4px solid #C53030; background: #FDF6EC;
        padding: 0.75rem 1rem; border-radius: 0.25rem; color: #2D3748;">
        <strong>Hour constraint violated:</strong><br>{violation_text}</div>""", unsafe_allow_html=True)

# --- Cost summary ---
st.markdown("### Cost Impact")
cost_df = edited[FORECAST_MONTHS].copy() * emp_rate
cost_df.insert(0, "Project Name", edited["Project Name"])

actual_costs = emp_data[["Project Name"] + [f"{m}_Cost" for m in ACTUAL_MONTHS]].copy()
actual_costs.columns = ["Project Name"] + ACTUAL_MONTHS

merged_cost = actual_costs.merge(cost_df, on="Project Name", how="right")
merged_cost["Full Year"] = merged_cost[ACTUAL_MONTHS + FORECAST_MONTHS].sum(axis=1)

st.dataframe(
    merged_cost.style.format({m: "${:,.0f}" for m in ACTUAL_MONTHS + FORECAST_MONTHS + ["Full Year"]}),
    use_container_width=True, hide_index=True,
)
total_fy = merged_cost["Full Year"].sum()
st.metric("Employee Full Year Cost", f"${total_fy:,.0f}")

# --- Project-Level Adjustments ---
st.markdown("---")
st.markdown("## Project-Level Adjustments")
st.caption("Set a target budget or hours for a project; hours auto-distribute across assigned employees proportionally.")

cost_cols = [f"{m}_Cost" for m in FORECAST_MONTHS]
proj_hours = labor_df.groupby(["Project Number", "Project Name"], as_index=False)[FORECAST_MONTHS].sum()
proj_hours["Total Forecast Hours"] = proj_hours[FORECAST_MONTHS].sum(axis=1)

proj_costs = labor_df.groupby(["Project Number", "Project Name"], as_index=False)[cost_cols].sum()
proj_costs["Total Forecast Cost"] = proj_costs[cost_cols].sum(axis=1)

proj_summary = proj_hours[["Project Number", "Project Name", "Total Forecast Hours"]].merge(
    proj_costs[["Project Number", "Total Forecast Cost"]], on="Project Number"
)
proj_summary = proj_summary.sort_values("Total Forecast Cost", ascending=False).reset_index(drop=True)

proj_options = proj_summary["Project Name"].tolist()
selected_proj = st.selectbox("Select Project to Adjust", proj_options, key="sp_proj")

proj_row = proj_summary[proj_summary["Project Name"] == selected_proj].iloc[0]
current_hours = proj_row["Total Forecast Hours"]
current_cost = proj_row["Total Forecast Cost"]

st.write(f"**Current forecast:** {current_hours:,.0f} hours / ${current_cost:,.0f}")

adj_mode = st.radio("Adjust by:", ["Target Hours", "Target Budget ($)"], horizontal=True, key="sp_adj_mode")

if adj_mode == "Target Hours":
    target_val = st.number_input("Target Total Hours (Apr-Dec)", value=float(current_hours), step=10.0, key="sp_tgt")
    scale_factor = target_val / current_hours if current_hours > 0 else 1.0
else:
    target_val = st.number_input("Target Budget ($)", value=float(current_cost), step=1000.0, key="sp_tgt")
    scale_factor = target_val / current_cost if current_cost > 0 else 1.0

if abs(scale_factor - 1.0) > 0.001:
    st.markdown(f"**Scale factor:** {scale_factor:.2%} of baseline")

    proj_emps = labor_df[labor_df["Project Name"] == selected_proj][
        ["Employee ID", "Employee Name", "Hourly Rate"] + FORECAST_MONTHS
    ].copy()

    for m in FORECAST_MONTHS:
        proj_emps[f"{m}_new"] = proj_emps[m] * scale_factor

    proj_emps["Baseline Hours"] = proj_emps[FORECAST_MONTHS].sum(axis=1)
    proj_emps["Adjusted Hours"] = proj_emps[[f"{m}_new" for m in FORECAST_MONTHS]].sum(axis=1)
    proj_emps["Adjusted Cost"] = proj_emps["Adjusted Hours"] * proj_emps["Hourly Rate"]
    proj_emps["Delta Hours"] = proj_emps["Adjusted Hours"] - proj_emps["Baseline Hours"]

    display_df = proj_emps[["Employee Name", "Baseline Hours", "Adjusted Hours", "Delta Hours", "Adjusted Cost"]]
    st.dataframe(
        display_df.style.format({"Baseline Hours": "{:,.1f}", "Adjusted Hours": "{:,.1f}",
                                 "Delta Hours": "{:+,.1f}", "Adjusted Cost": "${:,.0f}"}),
        use_container_width=True, hide_index=True,
    )

    new_total_cost = proj_emps["Adjusted Cost"].sum()
    st.metric("Adjusted Project Cost", f"${new_total_cost:,.0f}", delta=f"${new_total_cost - current_cost:+,.0f}")

    emp_totals = labor_df.groupby("Employee ID")[FORECAST_MONTHS].sum()
    violating_emps = []
    for _, row in proj_emps.iterrows():
        emp_id = row["Employee ID"]
        if emp_id in emp_totals.index:
            emp_base_total = emp_totals.loc[emp_id].sum()
            delta = row["Adjusted Hours"] - row["Baseline Hours"]
            new_monthly_avg = (emp_base_total + delta) / len(FORECAST_MONTHS)
            if abs(new_monthly_avg - 160) > 5:
                violating_emps.append(row["Employee Name"])
    if violating_emps:
        st.markdown(f"""<div style="border-left: 4px solid #D69E2E; background: #FDF6EC;
            padding: 0.75rem 1rem; border-radius: 0.25rem; color: #2D3748;">
            ⚠ Potential 160-hr constraint issue for: {', '.join(violating_emps)}</div>""",
            unsafe_allow_html=True)
else:
    st.info("Adjust the target to see redistribution preview.")

# --- Scenario Management ---
st.markdown("---")
st.markdown("## Scenario Management")

from utils.scenario_manager import list_scenarios, save_scenario, load_scenario, delete_scenario
from utils.forecast_engine import labor_monthly_summary

saved_scenarios = list_scenarios()

with st.expander("Save Current Scenario"):
    sc_name = st.text_input("Scenario Name", key="sc_name")
    sc_desc = st.text_input("Description", key="sc_desc")
    if st.button("Save Scenario", key="sc_save"):
        if sc_name:
            overrides = {}
            if f"edited_{selected_emp}" in st.session_state:
                editor_state = st.session_state[f"edited_{selected_emp}"]
                if isinstance(editor_state, dict) and "edited_rows" in editor_state:
                    overrides[selected_emp] = editor_state["edited_rows"]
            save_scenario(sc_name, sc_desc, overrides)
            st.success(f"Scenario '{sc_name}' saved.")
            st.rerun()
        else:
            st.warning("Enter a scenario name.")

if saved_scenarios:
    with st.expander("Load Scenario"):
        load_choice = st.selectbox("Select Scenario", saved_scenarios, key="sc_load_choice")
        if st.button("Load", key="sc_load_btn"):
            data = load_scenario(load_choice)
            st.session_state["active_scenario"] = data
            st.success(f"Loaded: {data['name']} - {data.get('description', '')}")

    with st.expander("Delete Scenario"):
        del_choice = st.selectbox("Select Scenario to Delete", saved_scenarios, key="sc_del_choice")
        if st.button("Delete", key="sc_del_btn"):
            delete_scenario(del_choice)
            st.success(f"Deleted: {del_choice}")
            st.rerun()

    if len(saved_scenarios) >= 2:
        st.markdown("### Compare Scenarios")
        col_a, col_b = st.columns(2)
        with col_a:
            sc_a = st.selectbox("Scenario A", saved_scenarios, key="sc_cmp_a")
        with col_b:
            sc_b = st.selectbox("Scenario B", saved_scenarios, index=min(1, len(saved_scenarios)-1), key="sc_cmp_b")

        if st.button("Compare", key="sc_cmp_btn"):
            data_a = load_scenario(sc_a)
            data_b = load_scenario(sc_b)

            baseline_summary = labor_monthly_summary(labor_df)
            baseline_fy = baseline_summary["Labor Cost"].sum()

            compare_df = pd.DataFrame({
                "Metric": ["Name", "Description", "Created", "Full Year Labor (Baseline)"],
                sc_a: [data_a["name"], data_a.get("description", ""), data_a.get("created_at", ""), f"${baseline_fy:,.0f}"],
                sc_b: [data_b["name"], data_b.get("description", ""), data_b.get("created_at", ""), f"${baseline_fy:,.0f}"],
            })
            st.dataframe(compare_df, use_container_width=True, hide_index=True)

            fig_cmp = go.Figure()
            monthly_costs = baseline_summary["Labor Cost"].tolist()
            fig_cmp.add_trace(go.Scatter(
                x=MONTHS, y=monthly_costs, mode="lines+markers",
                name=f"{sc_a} (baseline)", line=dict(color="#DD6B20"),
            ))
            fig_cmp.add_trace(go.Scatter(
                x=MONTHS, y=monthly_costs, mode="lines+markers",
                name=f"{sc_b} (baseline)", line=dict(color="#D69E2E", dash="dash"),
            ))
            fig_cmp.update_layout(
                yaxis_title="Cost ($)", template="plotly_white", height=350,
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig_cmp, use_container_width=True)
else:
    st.info("No saved scenarios yet. Use 'Save Current Scenario' above to create one.")
