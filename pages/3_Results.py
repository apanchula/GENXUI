from datetime import datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from pathlib import Path

import archive_lib
import report_lib
from src import ui, workspace
from src.resource_style import COLORS, resource_color  # noqa: F401  (COLORS used below)

st.set_page_config(page_title="GenX – Results", layout="wide")
ui.compact_layout()

if workspace.get_workspace_root() is None:
    st.title("Results")
    st.info("No workspace configured yet. Set one up from the **Runner** page first.")
    st.stop()

GENX_ROOT = workspace.legacy_genx_root()  # GenX.jl solver checkout, used only for git-commit tracking

# ── Sidebar ───────────────────────────────────────────────────────────────────
_archives = archive_lib.list_archives()
_pending_archive = st.session_state.pop("archive_to_view", None)

with st.sidebar:
    st.subheader("Source")

    source_options = ["Live case", "Archived run"]
    default_source = "Archived run" if _pending_archive else "Live case"
    source = st.radio("Data source", source_options, index=source_options.index(default_source))

    is_archived = source == "Archived run"
    archive_manifest: dict | None = None

    if is_archived:
        if not _archives:
            st.info("No archived runs yet. Archive a live run below to see it here.")
            st.stop()
        archive_labels = [
            f"{m['case_name']} — {m.get('label') or 'unlabeled'} — {m['archived_at'][:19]}"
            for m in _archives
        ]
        default_idx = 0
        if _pending_archive:
            for i, m in enumerate(_archives):
                if m.get("archive_dir_name") == _pending_archive:
                    default_idx = i
                    break
        sel_idx = st.selectbox(
            "Archived run", range(len(_archives)),
            format_func=lambda i: archive_labels[i], index=default_idx,
        )
        archive_manifest = _archives[sel_idx]
        case_name = archive_manifest["case_name"]
        results_dir = Path(archive_manifest["path"]) / "results"
        inputs_dir = Path(archive_manifest["path"]) / "inputs"
    else:
        cases = workspace.discover_cases()
        if not cases:
            st.info(f"No cases in `{workspace.data_dir()}`. Import one from the **Runner** page.")
            st.stop()
        _default_case = st.session_state.get("selected_case")
        _default_idx = cases.index(_default_case) if _default_case in cases else 0
        case_name = st.selectbox("Case", cases, index=_default_idx)
        case_path = workspace.data_dir() / case_name
        # GenX may have written results/, or results_1/, results_2/… — show the latest.
        results_dir = workspace.resolve_results_dir(case_path)
        inputs_dir = case_path

    if not is_archived:
        st.divider()
        st.markdown("**Archive this run**")
        if st.session_state.get("running"):
            st.caption("⚠ A run may be in progress — results shown could be stale.")
        archive_label = st.text_input("Label (optional)", key="archive_label_input")
        if st.button("📦 Archive this run", width="stretch"):
            try:
                archive_dir = archive_lib.create_archive(case_path, GENX_ROOT, label=archive_label)
                st.success(f"Archived to `{archive_dir.name}`")
            except archive_lib.ArchiveError as e:
                st.error(str(e))

    st.link_button(
        "📖 GenX Output Docs",
        "https://genxproject.github.io/GenX.jl/stable/User_Guide/model_output/",
        width="stretch",
    )

# ── Guard: no results yet ─────────────────────────────────────────────────────
if results_dir is None or not results_dir.exists():
    st.title("Results")
    st.info(
        f"No results found for **{case_name}**.  \n"
        "Run the model first from the **Runner** page."
    )
    st.stop()

# ── Data helpers ──────────────────────────────────────────────────────────────
@st.cache_data
def _read_csv(path_str: str, mtime: float) -> pd.DataFrame:
    return pd.read_csv(path_str)


def load(name: str) -> pd.DataFrame | None:
    p = results_dir / name
    if not p.exists():
        return None
    return _read_csv(str(p), p.stat().st_mtime)


costs_df      = load("costs.csv")
cap_df        = load("capacity.csv")
pb_df         = load("power_balance.csv")
rev_df        = load("NetRevenue.csv")
power_df      = load("power.csv")
charge_df     = load("charge.csv")
curtail_df    = load("curtailment.csv")
nse_df        = load("nse.csv")
prices_df     = load("prices.csv")


# ── Storage charging-source inference ────────────────────────────────────────
# GenX has no notion of "which generator charged storage" — it's a single zonal
# energy balance. This infers a likely source per hour by matching the zonal
# shadow price (prices.csv) against each candidate resource's known marginal
# cost, since that's the actual signal the LP used to make its dispatch choice.
@st.cache_data
def _compute_charging_source(inputs_dir_str: str, results_dir_str: str, cache_key: str) -> pd.DataFrame:
    inputs_p = Path(inputs_dir_str)
    results_p = Path(results_dir_str)

    def _read(p: Path):
        return pd.read_csv(p) if p.exists() else None

    thermal_df = _read(inputs_p / "resources" / "Thermal.csv")
    vre_df     = _read(inputs_p / "resources" / "Vre.csv")
    storage_df = _read(inputs_p / "resources" / "Storage.csv")
    fuels_df   = _read(inputs_p / "system" / "Fuels_data.csv")
    prices_in  = _read(results_p / "prices.csv")
    charge_in  = _read(results_p / "charge.csv")
    pb_in      = _read(results_p / "power_balance.csv")
    cap_in     = _read(results_p / "capacity.csv")

    empty = pd.DataFrame(columns=["Storage", "Hour", "Bucket", "MWh"])
    if any(df is None for df in (thermal_df, storage_df, fuels_df, prices_in, charge_in)):
        return empty

    _pc = prices_in.columns[0]
    price_ts = prices_in[prices_in[_pc].astype(str).str.match(r"^t\d+$")].reset_index(drop=True)
    T = len(price_ts)
    if T == 0:
        return empty
    hours = list(range(1, T + 1))
    price_ts.index = hours

    fuels_indexed = fuels_df.set_index("Time_Index")

    def _fuel_price_series(fuel_name):
        if fuel_name not in fuels_indexed.columns:
            return pd.Series(0.0, index=hours)
        s = fuels_indexed[fuel_name]
        return pd.Series([float(s.get(h, 0.0)) for h in hours], index=hours)

    thermal_cost = {}
    for _, row in thermal_df.iterrows():
        name = row["Resource"]
        zone = int(float(row["Zone"]))
        heat_rate = float(row.get("Heat_Rate_MMBTU_per_MWh", 0) or 0)
        var_om = float(row.get("Var_OM_Cost_per_MWh", 0) or 0)
        thermal_cost[name] = {
            "zone": zone,
            "cost": var_om + heat_rate * _fuel_price_series(row.get("Fuel")),
        }

    vre_zone = {}
    if vre_df is not None:
        vre_zone = {row["Resource"]: int(float(row["Zone"])) for _, row in vre_df.iterrows()}
    vre_zones_present = set(vre_zone.values())

    nse_by_zone = {}
    if pb_in is not None:
        _bc = pb_in.columns[0]
        zone_row = pb_in[pb_in[_bc].astype(str) == "Zone"]
        ts_rows = pb_in[pb_in[_bc].astype(str).str.match(r"^t\d+$")].reset_index(drop=True)
        ts_rows.index = hours
        if not zone_row.empty:
            zone_of_col = zone_row.iloc[0].to_dict()
            nse_cols = [c for c in pb_in.columns if c.split(".")[0] == "Nonserved_Energy"]
            zones_present = set()
            for c in nse_cols:
                try:
                    zones_present.add(int(float(zone_of_col[c])))
                except (TypeError, ValueError):
                    pass
            for zone in zones_present:
                cols = [c for c in nse_cols if int(float(zone_of_col[c])) == zone]
                nse_by_zone[zone] = pd.to_numeric(ts_rows[cols].sum(axis=1), errors="coerce").fillna(0.0)

    storage_zone = {row["Resource"]: int(float(row["Zone"])) for _, row in storage_df.iterrows()}

    # Exclude storage assets the model didn't actually build (zero energy capacity result)
    if cap_in is not None and "EndEnergyCap" in cap_in.columns:
        built_storage = set(cap_in[pd.to_numeric(cap_in["EndEnergyCap"], errors="coerce").fillna(0.0) > 0]["Resource"])
        storage_zone = {name: zone for name, zone in storage_zone.items() if name in built_storage}

    _chc = charge_in.columns[0]
    charge_ts = charge_in[charge_in[_chc].astype(str).str.match(r"^t\d+$")].reset_index(drop=True)
    charge_ts.index = hours

    TOL_REL = 0.02
    TOL_ABS = 0.5

    def _classify(price, candidates, nse):
        if nse > 1e-3:
            return "Reliability shortfall"
        best_name, best_diff = None, None
        for name, cost in candidates.items():
            diff = abs(price - cost)
            tol = max(TOL_ABS, TOL_REL * max(price, cost, 1))
            if diff <= tol and (best_diff is None or diff < best_diff):
                best_name, best_diff = name, diff
        return best_name if best_name else "Unclassified"

    records = []
    for stor_name, zone in storage_zone.items():
        if stor_name not in charge_ts.columns:
            continue
        zone_col = str(zone)
        if zone_col not in price_ts.columns:
            continue
        price_s = pd.to_numeric(price_ts[zone_col], errors="coerce").fillna(0.0)
        nse_s = nse_by_zone.get(zone)
        candidates = {name: info["cost"] for name, info in thermal_cost.items() if info["zone"] == zone}
        has_vre = zone in vre_zones_present
        charge_s = pd.to_numeric(charge_ts[stor_name], errors="coerce").fillna(0.0)

        for h in hours:
            c = charge_s[h]
            if c <= 1e-6:
                continue
            cand_at_h = {name: series[h] for name, series in candidates.items()}
            if has_vre:
                # A zero-price hour reveals surplus (otherwise-curtailed) VRE was the
                # marginal resource, even if leftover curtailment is exactly 0 that
                # hour because the charging itself absorbed what would've been curtailed.
                cand_at_h["Curtailed VRE"] = 0.0
            bucket = _classify(price_s[h], cand_at_h, nse_s[h] if nse_s is not None else 0.0)
            records.append({"Storage": stor_name, "Hour": h, "Bucket": bucket, "MWh": c})

    return pd.DataFrame(records, columns=["Storage", "Hour", "Bucket", "MWh"])

st.title(f"Results — {case_name}")
if is_archived and archive_manifest is not None:
    st.caption(
        f"Archived run — {archive_manifest.get('label') or 'unlabeled'} — "
        f"{archive_manifest['archived_at'][:19]} — "
        f"`{archive_lib.short_path(results_dir, workspace.archive_dir())}`"
    )
else:
    st.caption(f"Live case — `{archive_lib.short_path(results_dir, workspace.data_dir())}`")

# ── Section 1: Key Metrics ────────────────────────────────────────────────────
st.subheader("Key Metrics")

# Pre-compute NSE and demand totals (shared by the LCOE table and the cost metrics)
_nse_total_mwh = 0.0
if nse_df is not None:
    _fc = nse_df.columns[0]
    if "Total" in nse_df.columns:
        _r = nse_df[nse_df[_fc].astype(str) == "AnnualSum"]
        if not _r.empty:
            _v = pd.to_numeric(_r["Total"].iloc[0], errors="coerce")
            if pd.notna(_v):
                _nse_total_mwh = float(_v)
    elif "AnnualSum" in nse_df.columns:
        _r = nse_df[nse_df[_fc].astype(str) == "Total"]
        if not _r.empty:
            _v = pd.to_numeric(_r["AnnualSum"].iloc[0], errors="coerce")
            if pd.notna(_v):
                _nse_total_mwh = float(_v)
nse_gwh_total = _nse_total_mwh / 1e3

_demand_total_mwh = 0.0
if pb_df is not None:
    _fc = pb_df.columns[0]
    _demand_cols = [c for c in pb_df.columns if c.split(".")[0] == "Demand"]
    if _demand_cols:
        _r = pb_df[pb_df[_fc].astype(str) == "AnnualSum"]
        if not _r.empty:
            _v = pd.to_numeric(_r[_demand_cols].iloc[0], errors="coerce").fillna(0)
            _demand_total_mwh = abs(float(_v.sum()))
    elif "AnnualSum" in pb_df.columns:
        _rows = pb_df[pb_df[_fc].astype(str) == "Demand"]
        if not _rows.empty:
            _demand_total_mwh = abs(float(pd.to_numeric(_rows["AnnualSum"], errors="coerce").fillna(0).sum()))
demand_gwh_total = _demand_total_mwh / 1e3

lcoe_df: pd.DataFrame | None = None
lcoe_styler = None

# Levelized Cost of Energy per resource
if rev_df is not None and power_df is not None:
    rev  = rev_df[rev_df["Resource"].astype(str) != "Total"].copy()

    # power.csv is wide: rows are Zone/AnnualSum/timesteps, resource names are columns
    annual_row = power_df[power_df["Resource"] == "AnnualSum"]
    pwr = (
        annual_row
        .drop(columns=["Resource", "Total"], errors="ignore")
        .T
        .reset_index()
    )
    pwr.columns = ["Resource", "AnnualSum"]
    pwr["AnnualSum"] = pd.to_numeric(pwr["AnnualSum"], errors="coerce")

    # Identify storage/FLEX resources from charge.csv to exclude their charging from VRE gen-to-load
    storage_resources: set[str] = set()
    charge_by_resource: dict[str, float] = {}
    if charge_df is not None:
        charge_row = charge_df[charge_df["Resource"] == "AnnualSum"]
        if not charge_row.empty:
            for col in charge_df.columns:
                if col not in ("Resource", "Total"):
                    val = float(charge_row.iloc[0][col])
                    charge_by_resource[col] = val
                    if val > 0:
                        storage_resources.add(col)

    total_charge = sum(charge_by_resource.values())

    def _is_vre(name: str) -> bool:
        n = name.lower()
        return any(k in n for k in ("pv", "solar", "wind"))

    vre_resources = pwr[
        ~pwr["Resource"].isin(storage_resources) & pwr["Resource"].apply(_is_vre)
    ]["Resource"].tolist()
    vre_total_gen = pwr[pwr["Resource"].isin(vre_resources)]["AnnualSum"].sum()

    def _gen_to_load(resource: str, annual_sum: float) -> float:
        if resource in storage_resources:
            return annual_sum                          # discharge → load
        if _is_vre(resource):
            vre_share = annual_sum / vre_total_gen if vre_total_gen > 0 else 0.0
            return max(0.0, annual_sum - total_charge * vre_share)  # subtract charging share
        return annual_sum

    pwr["_gen_to_load"] = pwr.apply(
        lambda r: _gen_to_load(r["Resource"], r["AnnualSum"]), axis=1
    )

    # Curtailment per resource (same wide format as power.csv)
    curtail_by_resource: dict[str, float] = {}
    if curtail_df is not None:
        curtail_row = curtail_df[curtail_df["Resource"] == "AnnualSum"]
        if not curtail_row.empty:
            for col in curtail_df.columns:
                if col not in ("Resource", "Total"):
                    curtail_by_resource[col] = float(curtail_row.iloc[0][col])

    # _total_cost (used for LCOE) includes charging cost; Hardware Cost breaks out
    # the non-charging portion so charging cost isn't double-counted between the two.
    rev["_total_cost"] = rev["Cost"]
    if "Charge_cost" in rev.columns:
        _charge_cost_by_resource = dict(zip(rev["Resource"], rev["Charge_cost"]))
    else:
        _charge_cost_by_resource = {}
    lcoe_df = rev[["Resource", "_total_cost"]].merge(pwr, on="Resource", how="left")
    lcoe_df["Hardware Cost ($M/yr)"] = (
        lcoe_df["_total_cost"] - lcoe_df["Resource"].map(_charge_cost_by_resource).fillna(0)
    ) / 1e6
    lcoe_df["Charging Cost ($M/yr)"] = lcoe_df["Resource"].map(
        lambda r: _charge_cost_by_resource.get(r, 0.0) / 1e6 if _charge_cost_by_resource.get(r, 0.0) > 0 else None
    )
    lcoe_df["Curtailment (GWh/yr)"] = lcoe_df["Resource"].map(
        lambda r: curtail_by_resource.get(r, 0.0) / 1e3
    )
    # Annual Gen = dispatch + curtailment  (total potential generation)
    # Gen to Load = dispatch - charging share  (excludes what went to charge storage)
    # Identity: Annual Gen = Gen to Load + Curtailment + Battery Charging
    lcoe_df["Gen to Load (GWh/yr)"] = lcoe_df["_gen_to_load"] / 1e3
    lcoe_df["Annual Gen (GWh/yr)"]  = lcoe_df["AnnualSum"] / 1e3 + lcoe_df["Curtailment (GWh/yr)"]
    lcoe_df["Curtail %"] = lcoe_df.apply(
        lambda r: 100 * r["Curtailment (GWh/yr)"] / r["Annual Gen (GWh/yr)"]
        if r["Annual Gen (GWh/yr)"] > 0 else None,
        axis=1,
    )
    lcoe_df["LCOE ($/MWh)"] = lcoe_df.apply(
        lambda r: r["_total_cost"] / r["AnnualSum"] if r["AnnualSum"] > 0 else None,
        axis=1,
    )
    lcoe_df = lcoe_df[[
        "Resource", "LCOE ($/MWh)", "Hardware Cost ($M/yr)", "Charging Cost ($M/yr)",
        "Annual Gen (GWh/yr)", "Gen to Load (GWh/yr)",
        "Curtailment (GWh/yr)", "Curtail %",
    ]]

    # ── Aggregate rows ─────────────────────────────────────────────────────────
    # DR Gen to Load: Demand_Response summed across all zones
    _dr_gen_gwh = 0.0
    if pb_df is not None:
        _fc = pb_df.columns[0]
        _ann = pb_df[pb_df[_fc].astype(str) == "AnnualSum"]
        if not _ann.empty:
            _dr_cols = [c for c in pb_df.columns if "Demand_Response" in str(c)]
            if _dr_cols:
                _v = pd.to_numeric(_ann[_dr_cols].iloc[0], errors="coerce").fillna(0)
                _dr_gen_gwh = abs(float(_v.sum())) / 1e3

    # DR Annual Cost: resources with "flex" in name (case-insensitive)
    _dr_cost_m = 0.0
    if rev_df is not None:
        _flex_rows = rev_df[
            rev_df["Resource"].astype(str).str.lower().str.contains("flex", na=False) &
            (rev_df["Resource"].astype(str) != "Total")
        ]
        if not _flex_rows.empty:
            _dr_cost_m = float(pd.to_numeric(_flex_rows["Cost"], errors="coerce").fillna(0).sum()) / 1e6

    _dr_lcoe = _dr_cost_m * 1e6 / (_dr_gen_gwh * 1e3) if _dr_gen_gwh > 0 else None

    # Nonserved Energy Gen to Load: Nonserved_Energy summed across all zones
    _nse_gen_gwh = 0.0
    if pb_df is not None:
        _fc = pb_df.columns[0]
        _ann = pb_df[pb_df[_fc].astype(str) == "AnnualSum"]
        if not _ann.empty:
            _nse_cols = [c for c in pb_df.columns if "Nonserved_Energy" in str(c)]
            if _nse_cols:
                _v = pd.to_numeric(_ann[_nse_cols].iloc[0], errors="coerce").fillna(0)
                _nse_gen_gwh = abs(float(_v.sum())) / 1e3

    # Unserved Energy annual cost = cNSE from costs.csv (matches the Key Metrics tile)
    _nse_cost_m = 0.0
    if costs_df is not None:
        _costs_series = costs_df.set_index("Costs")["Total"]
        _nse_cost_m = float(_costs_series.get("cNSE", 0)) / 1e6
    _nse_lcoe = _nse_cost_m * 1e6 / (_nse_gen_gwh * 1e3) if _nse_gen_gwh > 0 else None

    extra_rows = pd.DataFrame([
        {
            "Resource":               "Demand Response",
            "LCOE ($/MWh)":           _dr_lcoe,
            "Hardware Cost ($M/yr)":  _dr_cost_m if _dr_cost_m > 0 else None,
            "Charging Cost ($M/yr)":  None,
            "Annual Gen (GWh/yr)":    None,
            "Gen to Load (GWh/yr)":   _dr_gen_gwh,
            "Curtailment (GWh/yr)":   None,
            "Curtail %":              None,
        },
        {
            "Resource":               "Unserved Energy",
            "LCOE ($/MWh)":           _nse_lcoe,
            "Hardware Cost ($M/yr)":  _nse_cost_m if _nse_cost_m > 0 else None,
            "Charging Cost ($M/yr)":  None,
            "Annual Gen (GWh/yr)":    None,
            "Gen to Load (GWh/yr)":   _nse_gen_gwh,
            "Curtailment (GWh/yr)":   None,
            "Curtail %":              None,
        },
    ])
    lcoe_df = pd.concat([lcoe_df, extra_rows], ignore_index=True)

    # ── Total row ────────────────────────────────────────────────────────────
    _total_hw           = lcoe_df["Hardware Cost ($M/yr)"].sum(skipna=True)
    _total_charge_cost  = lcoe_df["Charging Cost ($M/yr)"].sum(skipna=True)
    _total_gen_to_load  = lcoe_df["Gen to Load (GWh/yr)"].sum(skipna=True)
    _total_lcoe = (
        (_total_hw + _total_charge_cost) * 1e6 / (_total_gen_to_load * 1e3)
        if _total_gen_to_load > 0 else None
    )
    total_row = pd.DataFrame([{
        "Resource":               "Total",
        "LCOE ($/MWh)":           _total_lcoe,
        "Hardware Cost ($M/yr)":  _total_hw,
        "Charging Cost ($M/yr)":  _total_charge_cost if _total_charge_cost > 0 else None,
        "Annual Gen (GWh/yr)":    None,
        "Gen to Load (GWh/yr)":   _total_gen_to_load,
        "Curtailment (GWh/yr)":   None,
        "Curtail %":              None,
    }])
    lcoe_df = pd.concat([lcoe_df, total_row], ignore_index=True)

    def _bold_total_row(row):
        style = "font-weight: bold" if row["Resource"] == "Total" else ""
        return [style] * len(row)

    lcoe_styler = lcoe_df.style.apply(_bold_total_row, axis=1)

    st.dataframe(
        lcoe_styler,
        hide_index=True,
        width="stretch",
        column_config={
            "LCOE ($/MWh)":           st.column_config.NumberColumn(format="$%.2f"),
            "Hardware Cost ($M/yr)":  st.column_config.NumberColumn(format="$%.3f"),
            "Charging Cost ($M/yr)":  st.column_config.NumberColumn(format="$%.3f"),
            "Annual Gen (GWh/yr)":    st.column_config.NumberColumn(format="%.1f"),
            "Gen to Load (GWh/yr)":   st.column_config.NumberColumn(format="%.1f"),
            "Curtailment (GWh/yr)":   st.column_config.NumberColumn(format="%.1f"),
            "Curtail %":              st.column_config.NumberColumn(format="%.1f%%"),
        },
    )
    st.divider()

# Redundant with the LCOE table's Total row above (Hardware Cost + Charging Cost
# covers cFix/cVar/cFuel, and the Unserved Energy row covers cNSE).
# if costs_df is not None:
#     costs = costs_df.set_index("Costs")["Total"]
#     c_fix   = float(costs.get("cFix",   0)) / 1e6
#     c_var   = float(costs.get("cVar",   0)) / 1e6
#     c_fuel  = float(costs.get("cFuel",  0)) / 1e6
#     c_nse   = float(costs.get("cNSE",   0)) / 1e6
#     # Unserved energy cost is broken out in its own metric below, so exclude it
#     # here to avoid double-counting it in the headline total.
#     c_total = float(costs.get("cTotal", 0)) / 1e6 - c_nse
#
#     def pct(val):
#         return f"{100 * val / c_total:.1f}% of total" if c_total else ""
#
#     nse_pct = 100.0 * nse_gwh_total / demand_gwh_total if demand_gwh_total > 0 else 0.0
#     nse_delta = f"{nse_gwh_total:.2f} GWh  ({nse_pct:.3f}% of load)"
#
#     col1, col2, col3, col4 = st.columns(4)
#     col1.metric("Total System Cost",  f"${c_total:.2f}M/yr")
#     col2.metric("Fixed Cost",         f"${c_fix:.2f}M/yr",         pct(c_fix))
#     col3.metric("Variable + Fuel",    f"${c_var + c_fuel:.2f}M/yr", pct(c_var + c_fuel))
#     col4.metric("Unserved Energy",    f"${c_nse:.4f}M/yr",          nse_delta, delta_color="off")
# else:
#     st.warning("`costs.csv` not found in results.")
#
# st.divider()

# ── Section 2: Capacity + Power Balance ──────────────────────────────────────
cap_fig = None
pie_fig = None

col_cap, col_pb = st.columns(2)

with col_cap:
    st.subheader("Capacity Built")
    if cap_df is not None:
        cap = cap_df[cap_df["Resource"].astype(str) != "Total"].copy()
        colors = [resource_color(r) for r in cap["Resource"]]

        cap_fig = go.Figure()
        cap_fig.add_trace(go.Bar(
            name="Power (MW)",
            x=cap["Resource"],
            y=cap["EndCap"],
            marker_color=colors,
        ))

        stor = cap[cap["EndEnergyCap"] > 0]
        if not stor.empty:
            cap_fig.add_trace(go.Bar(
                name="Energy (MWh)",
                x=stor["Resource"],
                y=stor["EndEnergyCap"],
                marker_color="#1a7a4a",
                opacity=0.65,
            ))

        cap_fig.update_layout(
            barmode="group",
            yaxis_title="Capacity",
            xaxis_tickangle=-20,
            height=340,
            margin=dict(t=5, b=5, l=0, r=0),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        st.plotly_chart(cap_fig, width="stretch")

        # Storage metrics: demand, power, energy, duration
        if not stor.empty:
            def _small_metric(col, label, value):
                col.markdown(
                    f"<div style='font-size:0.75rem;color:grey;margin-bottom:2px'>{label}</div>"
                    f"<div style='font-size:0.95rem;font-weight:600'>{value}</div>",
                    unsafe_allow_html=True,
                )

            for _, row in stor.iterrows():
                st.markdown(
                    f"<div style='font-weight:600;font-size:0.9rem;"
                    f"margin:0.6rem 0 -0.5rem'>{row['Resource']}</div>",
                    unsafe_allow_html=True,
                )
                m1, m2, m3, m4, m5 = st.columns(5)
                bat_discharge_power = row["EndCap"]
                bat_charge_cap      = row.get("EndChargeCap", 0.0) or 0.0
                # Symmetric storage has no separate charge investment (EndChargeCap == 0),
                # so its charge power equals its discharge power rating.
                bat_charge_power = bat_charge_cap if bat_charge_cap > 0 else bat_discharge_power
                bat_energy = row["EndEnergyCap"]
                bat_dur    = bat_energy / bat_discharge_power if bat_discharge_power > 0 else 0
                bat_charge_time = bat_energy / bat_charge_power if bat_charge_power > 0 else 0
                _small_metric(m1, "Discharge Power",    f"{bat_discharge_power:.1f} MW")
                _small_metric(m2, "Charge Power",       f"{bat_charge_power:.1f} MW")
                _small_metric(m3, "Battery Energy",     f"{bat_energy:.1f} MWh")
                _small_metric(m4, "Battery Duration",   f"{bat_dur:.1f} h")
                _small_metric(m5, "Min Charge Time",    f"{bat_charge_time:.1f} h")
    else:
        st.warning("`capacity.csv` not found.")


with col_pb:
    st.subheader("Supply to Load Mix")
    if lcoe_df is not None:
        pie_rows = lcoe_df[
            (lcoe_df["Gen to Load (GWh/yr)"] > 0) & (lcoe_df["Resource"] != "Total")
        ].copy()
        labels     = pie_rows["Resource"].tolist()
        values     = pie_rows["Gen to Load (GWh/yr)"].tolist()
        pie_colors = [resource_color(r) for r in labels]

        pie_fig = go.Figure(go.Pie(
            labels=labels,
            values=values,
            hole=0.38,
            marker_colors=pie_colors,
            textinfo="label+percent",
            textposition="outside",
        ))
        pie_fig.update_layout(
            height=380,
            margin=dict(t=30, b=80, l=0, r=100),
            showlegend=False,
        )
        st.plotly_chart(pie_fig, width="stretch")
    else:
        st.warning("Run the model to see generation mix.")

st.divider()

# ── Section 3: Unserved Energy Timing ─────────────────────────────────────────
st.subheader("Unserved Energy by Time of Year")

nse_fig = None

if nse_df is not None:
    _fc = nse_df.columns[0]
    ts = nse_df[nse_df[_fc].astype(str).str.match(r"^t\d+$")]
    if "Total" in ts.columns:
        nse_series = pd.to_numeric(ts["Total"], errors="coerce").fillna(0).reset_index(drop=True)
    else:
        nse_series = pd.Series(dtype=float)

    n_hours = len(nse_series)
    if n_hours == 8760 and nse_series.sum() > 0:
        # Reshape into a 365-day x 24-hour grid (assumes a non-leap hourly year starting Jan 1)
        grid = nse_series.values.reshape(365, 24).T

        month_starts = [1, 32, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335]
        month_labels = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                         "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

        nse_fig = go.Figure(go.Heatmap(
            z=grid,
            x=list(range(1, 366)),
            y=list(range(24)),
            colorscale=[[0, "#1a7a4a"], [1, "#ffffff"]],  # was: colorscale="Reds"
            colorbar=dict(title="MW"),
        ))
        nse_fig.update_layout(
            xaxis=dict(title="Month", tickvals=month_starts, ticktext=month_labels),
            yaxis=dict(title="Hour of Day", dtick=4),
            height=320,
            margin=dict(t=5, b=5, l=0, r=0),
        )
        st.plotly_chart(nse_fig, width="stretch")
    elif n_hours > 0 and nse_series.sum() > 0:
        nse_fig = px.area(
            x=range(1, n_hours + 1), y=nse_series.values,
            labels={"x": "Timestep", "y": "MW"},
        )
        nse_fig.update_layout(height=280, margin=dict(t=5, b=5, l=0, r=0))
        st.plotly_chart(nse_fig, width="stretch")
        st.caption(
            f"{n_hours} timesteps found (not a full 8760-hour year), "
            "showing unserved energy over the modeled period instead of a calendar heatmap."
        )
    else:
        st.caption("No unserved energy in this case.")
else:
    st.caption("`nse.csv` not found.")

st.divider()

# ── Section 4: Cost Breakdown ─────────────────────────────────────────────────
st.subheader("Cost Breakdown by Resource")

cost_fig = None

if rev_df is not None:
    rev = rev_df[rev_df["Resource"].astype(str) != "Total"].copy()
    M = 1e6

    inv_cols  = [c for c in ["Inv_cost_MW", "Inv_cost_MWh", "Inv_cost_charge_MW"] if c in rev.columns]
    fom_cols  = [c for c in ["Fixed_OM_cost_MW", "Fixed_OM_cost_MWh", "Fixed_OM_cost_charge_MW"] if c in rev.columns]
    vom_cols  = [c for c in ["Var_OM_cost_out", "Var_OM_cost_in"] if c in rev.columns]
    fuel_cols = [c for c in ["Fuel_cost"] if c in rev.columns]
    start_cols = [c for c in ["StartCost"] if c in rev.columns]
    other_cols = [c for c in ["CO2SequestrationCost", "EmissionsCost"] if c in rev.columns]

    rev = rev.copy()
    rev["Investment"]  = rev[inv_cols].sum(axis=1)   / M if inv_cols   else 0.0
    rev["Fixed O&M"]   = rev[fom_cols].sum(axis=1)   / M if fom_cols   else 0.0
    rev["Variable O&M"]= rev[vom_cols].sum(axis=1)   / M if vom_cols   else 0.0
    rev["Fuel"]        = rev[fuel_cols].sum(axis=1)  / M if fuel_cols  else 0.0
    rev["Startup"]     = rev[start_cols].sum(axis=1) / M if start_cols else 0.0
    rev["Other"]       = rev[other_cols].sum(axis=1) / M if other_cols else 0.0

    breakdown_cols = ["Investment", "Fixed O&M", "Variable O&M", "Fuel", "Startup", "Other"]
    melted = rev[["Resource"] + breakdown_cols].melt(
        id_vars="Resource", var_name="Cost Type", value_name="$M/yr"
    )
    melted = melted[melted["$M/yr"].abs() > 0]

    color_seq = ["#4682b4", "#87ceeb", "#ff8c00", "#b22222", "#9b59b6", "#888888"]
    cost_fig = px.bar(
        melted,
        x="Resource",
        y="$M/yr",
        color="Cost Type",
        color_discrete_sequence=color_seq,
        barmode="stack",
    )
    cost_fig.update_layout(
        yaxis_title="$M / yr",
        xaxis_tickangle=-20,
        height=360,
        margin=dict(t=5, b=5, l=0, r=0),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    st.plotly_chart(cost_fig, width="stretch")
else:
    st.warning("`NetRevenue.csv` not found.")

st.divider()

# ── Section 4b: Hourly Curtailment ────────────────────────────────────────────
st.subheader("Hourly Curtailment")

if curtail_df is not None:
    _fc = curtail_df.columns[0]
    curt_ts = curtail_df[curtail_df[_fc].astype(str).str.match(r"^t\d+$")].copy()
    series_cols = [c for c in curt_ts.columns if c != _fc and "pv" in c.lower()]
    if not curt_ts.empty and series_cols:
        curt_ts["Hour"] = curt_ts[_fc].astype(str).str[1:].astype(int)
        for c in series_cols:
            curt_ts[c] = pd.to_numeric(curt_ts[c], errors="coerce")
        plot_df = curt_ts[["Hour"] + series_cols].dropna(how="all", subset=series_cols)
        step = max(1, len(plot_df) // 500)
        sampled = plot_df.iloc[::step]

        curt_fig = px.line(sampled, x="Hour", y=series_cols, labels={"value": "MW"})
        curt_fig.update_layout(
            height=250,
            margin=dict(t=5, b=5, l=0, r=0),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, title=None),
        )
        st.plotly_chart(curt_fig, width="stretch")
    else:
        st.caption("No hourly PV curtailment data found.")
else:
    st.caption("`curtailment.csv` not found.")

st.divider()

# ── Section 4c: Hourly Power by Resource ──────────────────────────────────────
st.subheader("Hourly Power by Resource")

if power_df is not None:
    _fc = power_df.columns[0]
    pwr_ts = power_df[power_df[_fc].astype(str).str.match(r"^t\d+$")].copy()
    resource_cols = [c for c in power_df.columns if c != _fc]
    if not pwr_ts.empty and resource_cols:
        selected_resource = st.selectbox("Resource", resource_cols, key="power_resource_select")
        pwr_ts["Hour"] = pwr_ts[_fc].astype(str).str[1:].astype(int)
        pwr_ts[selected_resource] = pd.to_numeric(pwr_ts[selected_resource], errors="coerce")
        plot_df = pwr_ts[["Hour", selected_resource]].dropna(subset=[selected_resource])
        step = max(1, len(plot_df) // 500)
        sampled = plot_df.iloc[::step]

        power_fig = px.line(sampled, x="Hour", y=selected_resource, labels={selected_resource: "MW"})
        power_fig.update_layout(height=280, margin=dict(t=5, b=5, l=0, r=0))
        st.plotly_chart(power_fig, width="stretch")
    else:
        st.caption("No hourly power data found.")
else:
    st.caption("`power.csv` not found.")

st.divider()

# ── Section 4d: Storage Charging Source ───────────────────────────────────────
st.subheader("Storage Charging Source")
st.caption(
    "GenX doesn't track which generator's energy charges storage — it's a single "
    "zonal energy balance. This infers a likely source per hour by matching the "
    "zonal shadow price against each resource's known marginal cost. Treat this as "
    "a derived economic interpretation, not a physically tracked flow."
)

_source_mtimes = []
for _rel in ["resources/Thermal.csv", "resources/Vre.csv", "resources/Storage.csv", "system/Fuels_data.csv"]:
    _p = inputs_dir / _rel
    if _p.exists():
        _source_mtimes.append(_p.stat().st_mtime)
for _rel in ["prices.csv", "charge.csv", "power_balance.csv", "capacity.csv"]:
    _p = results_dir / _rel
    if _p.exists():
        _source_mtimes.append(_p.stat().st_mtime)
_source_cache_key = str(max(_source_mtimes)) if _source_mtimes else "0"

charge_source_df = _compute_charging_source(str(inputs_dir), str(results_dir), _source_cache_key)

if charge_source_df.empty:
    st.caption(
        "Need `prices.csv`, `charge.csv`, and case inputs (Thermal.csv, Storage.csv, "
        "Fuels_data.csv) to derive charging source."
    )
else:
    _summary = charge_source_df.groupby(["Storage", "Bucket"])["MWh"].sum().reset_index()
    _pivot = _summary.pivot(index="Bucket", columns="Storage", values="MWh").fillna(0.0)
    _pct = _pivot.div(_pivot.sum(axis=0), axis=1) * 100
    _pivot_with_total = pd.concat([_pivot, _pivot.sum(axis=0).to_frame("Total").T])

    col_src_tab, col_src_chart = st.columns([1, 1.4])

    with col_src_tab:
        st.caption("Annual charging by inferred source (MWh)")
        st.dataframe(_pivot_with_total.style.format("{:,.0f}"), width="stretch")
        st.caption("Share of each resource's total charging (%)")
        st.dataframe(_pct.style.format("{:,.1f}%"), width="stretch")

    with col_src_chart:
        _stor_options = sorted(charge_source_df["Storage"].unique())
        _sel_stor = st.selectbox("Storage resource", _stor_options, key="charge_source_resource")

        _sub = charge_source_df[charge_source_df["Storage"] == _sel_stor].copy()
        _sub["Day"] = ((_sub["Hour"] - 1) // 24) + 1
        _daily = _sub.groupby(["Day", "Bucket"], as_index=False)["MWh"].sum()

        _bucket_colors = {
            "Curtailed VRE": "#27ae60",
            "Reliability shortfall": "#b22222",
            "Unclassified": "#888888",
        }
        _color_map = {b: _bucket_colors.get(b, resource_color(b)) for b in _daily["Bucket"].unique()}

        source_fig = px.bar(_daily, x="Day", y="MWh", color="Bucket", color_discrete_map=_color_map)
        source_fig.update_layout(
            barmode="stack",
            yaxis_title="MWh/day",
            height=320,
            margin=dict(t=5, b=5, l=0, r=0),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, title=None),
        )
        st.plotly_chart(source_fig, width="stretch")

    st.caption(
        "Classification matches each hour's zonal shadow price to a resource's "
        "marginal cost (±2% or $0.50 tolerance). 'Unclassified' hours had a price "
        "that didn't clearly match any candidate — often solver-tolerance noise or "
        "degenerate unit-commitment pricing."
    )

st.divider()

# ── Export ────────────────────────────────────────────────────────────────────
st.subheader("Export")

_report_styler = None
if lcoe_df is not None:
    _report_styler = lcoe_df.style.apply(_bold_total_row, axis=1).format(
        {
            "LCOE ($/MWh)":           "${:.2f}",
            "Hardware Cost ($M/yr)":  "${:.3f}",
            "Charging Cost ($M/yr)":  "${:.3f}",
            "Annual Gen (GWh/yr)":    "{:.1f}",
            "Gen to Load (GWh/yr)":   "{:.1f}",
            "Curtailment (GWh/yr)":   "{:.1f}",
            "Curtail %":              "{:.1f}%",
        },
        na_rep="",
    )

_report_html = report_lib.build_results_html(
    case_label=case_name,
    generated_at=datetime.now(),
    lcoe_styler=_report_styler,
    cap_fig=cap_fig,
    pie_fig=pie_fig,
    nse_fig=nse_fig,
    cost_fig=cost_fig,
)
st.download_button(
    "⬇ Export report (HTML)",
    data=_report_html,
    file_name=f"genx_results_{case_name}_{datetime.now():%Y%m%d-%H%M%S}.html",
    mime="text/html",
)

st.divider()

# ── Section 5: Raw Data ───────────────────────────────────────────────────────
st.subheader("Raw Data")

raw_files = {
    "costs.csv":          costs_df,
    "capacity.csv":       cap_df,
    "power.csv":          power_df,
    "curtailment.csv":    curtail_df,
    "power_balance.csv":  pb_df,
    "NetRevenue.csv":     rev_df,
}

for fname, df in raw_files.items():
    with st.expander(f"📄 {fname}"):
        if df is not None:
            st.dataframe(df, width="stretch")
        else:
            st.caption("File not found.")
