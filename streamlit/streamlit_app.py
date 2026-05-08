import streamlit as st
import pandas as pd
import plotly.express as px
from supabase import create_client, Client  # supabase-py

st.set_page_config(page_title="SIOP Executive Dashboard", layout="wide")

# --- Secrets (Streamlit Cloud: set in App > Settings > Secrets)
SUPABASE_URL = st.secrets.get("SUPABASE_URL", "")
SUPABASE_KEY = st.secrets.get("SUPABASE_KEY", "")

if not SUPABASE_URL or not SUPABASE_KEY:
    st.error("Missing SUPABASE_URL / SUPABASE_KEY in Streamlit secrets.")
    st.stop()

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)  # official init pattern [5](https://supabase.com/docs/reference/python/start)

st.title("SIOP — Executive Summary (Streamlit)")
st.caption("Scenario-driven view across Plants / Business Groups with gap, inventory, DOH and utilisation.")

@st.cache_data(ttl=300)
def fetch_table(table: str, cols="*"):
    resp = supabase.table(table).select(cols).execute()
    return pd.DataFrame(resp.data or [])

@st.cache_data(ttl=300)
def fetch_kpis(scenario_id: str, plant_id: str | None):
    q = supabase.table("kpi_snapshots").select("*").eq("scenario_id", scenario_id)
    if plant_id:
        q = q.eq("plant_id", plant_id)
    resp = q.execute()
    return pd.DataFrame(resp.data or [])

def compute_kpis_from_plans(scenario_id: str, plant_id: str | None):
    # Minimal fallback aggregation (monthly)
    d_q = supabase.table("demand_plan").select("period_month,demand_qty,plant_id").eq("scenario_id", scenario_id)
    s_q = supabase.table("supply_plan").select("period_month,capacity_qty,planned_prod_qty,constrained_prod_qty,plant_id").eq("scenario_id", scenario_id)
    i_q = supabase.table("inventory_plan").select("period_month,closing_qty,doh,plant_id").eq("scenario_id", scenario_id)

    if plant_id:
        d_q = d_q.eq("plant_id", plant_id)
        s_q = s_q.eq("plant_id", plant_id)
        i_q = i_q.eq("plant_id", plant_id)

    d = pd.DataFrame((d_q.execute().data or []))
    s = pd.DataFrame((s_q.execute().data or []))
    i = pd.DataFrame((i_q.execute().data or []))

    if d.empty and s.empty and i.empty:
        return pd.DataFrame()

    # Normalise
    for df in (d, s, i):
        if not df.empty:
            df["period_month"] = pd.to_datetime(df["period_month"]).dt.date.astype(str)

    # Aggregate
    out = pd.DataFrame({"period_month": sorted(set(
        (d["period_month"].tolist() if not d.empty else []) +
        (s["period_month"].tolist() if not s.empty else []) +
        (i["period_month"].tolist() if not i.empty else [])
    ))})

    if not d.empty:
        d_agg = d.groupby("period_month", as_index=False)["demand_qty"].sum()
        out = out.merge(d_agg, on="period_month", how="left")
    else:
        out["demand_qty"] = 0

    if not s.empty:
        s["supply_qty"] = s["constrained_prod_qty"].fillna(s["planned_prod_qty"]).fillna(0)
        s_agg = s.groupby("period_month", as_index=False)[["supply_qty","capacity_qty"]].sum()
        out = out.merge(s_agg, on="period_month", how="left")
    else:
        out["supply_qty"] = 0
        out["capacity_qty"] = 0

    if not i.empty:
        i_agg = i.groupby("period_month", as_index=False).agg(
            closing_inventory_qty=("closing_qty", "sum"),
            avg_doh=("doh", "mean")
        )
        out = out.merge(i_agg, on="period_month", how="left")
    else:
        out["closing_inventory_qty"] = 0
        out["avg_doh"] = 0

    out = out.fillna(0)
    out["gap_qty"] = out["supply_qty"] - out["demand_qty"]
    out["capacity_utilisation_pct"] = out.apply(lambda r: (r["supply_qty"]/r["capacity_qty"]*100) if r["capacity_qty"] else 0, axis=1)

    return out

# --- Load master data for filters
plants = fetch_table("plants", "id,plant_name,country,business_group_id")
scenarios = fetch_table("scenarios", "id,name,scenario_type,created_at")

if scenarios.empty:
    st.warning("No scenarios found. Create a BASELINE scenario in Supabase first.")
    st.stop()

# Sidebar filters
st.sidebar.header("Filters")
scenario_id = st.sidebar.selectbox(
    "Scenario",
    options=scenarios["id"].tolist(),
    format_func=lambda x: f"{scenarios.loc[scenarios['id']==x,'name'].values[0]} ({scenarios.loc[scenarios['id']==x,'scenario_type'].values[0]})"
)

plant_choice = st.sidebar.selectbox(
    "Plant",
    options=["ALL"] + (plants["id"].tolist() if not plants.empty else []),
    format_func=lambda x: "All plants" if x == "ALL" else f"{plants.loc[plants['id']==x,'plant_name'].values[0]} ({plants.loc[plants['id']==x,'country'].values[0]})"
)

plant_id = None if plant_choice == "ALL" else plant_choice

# --- KPI load (snapshots first)
kpis = fetch_kpis(scenario_id, plant_id)
use_snapshots = not kpis.empty

if not use_snapshots:
    st.info("kpi_snapshots empty for this selection — computing KPIs from plan tables (slower).")
    kpis = compute_kpis_from_plans(scenario_id, plant_id)

if kpis.empty:
    st.warning("No KPI / plan data found for this selection.")
    st.stop()

# Normalise month column
kpis["period_month"] = pd.to_datetime(kpis["period_month"]).dt.date.astype(str)
kpis = kpis.sort_values("period_month")

# Headline (last month)
last = kpis.iloc[-1]
months_short = int((kpis["gap_qty"] < 0).sum()) if "gap_qty" in kpis else 0

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Demand", f"{last.get('demand_qty',0):,.0f}")
c2.metric("Supply", f"{last.get('supply_qty',0):,.0f}")
c3.metric("Gap (S-D)", f"{last.get('gap_qty',0):,.0f}")
c4.metric("Inventory", f"{last.get('closing_inventory_qty',0):,.0f}")
c5.metric("Avg DOH", f"{last.get('avg_doh',0):,.1f}")

st.divider()

# Charts row
left, right = st.columns([2, 1])

with left:
    st.subheader("Demand vs Supply")
    fig = px.line(
        kpis,
        x="period_month",
        y=["demand_qty","supply_qty"],
        markers=True,
        labels={"value":"Qty","period_month":"Month","variable":"Metric"},
    )
    st.plotly_chart(fig, use_container_width=True)

with right:
    st.subheader("Decision Focus")
    st.write(f"Months with shortage (gap < 0): **{months_short}**")
    fig2 = px.bar(
        kpis,
        x="period_month",
        y="capacity_utilisation_pct",
        labels={"capacity_utilisation_pct":"Utilisation %","period_month":"Month"},
    )
    st.plotly_chart(fig2, use_container_width=True)

st.subheader("Inventory & DOH")
fig3 = px.line(
    kpis,
    x="period_month",
    y=["closing_inventory_qty","avg_doh"],
    markers=True,
    labels={"value":"Value","period_month":"Month","variable":"Metric"},
)
st.plotly_chart(fig3, use_container_width=True)

with st.expander("Data table"):
    st.dataframe(kpis, use_container_width=True)
