"""Tests for src/metrics.py — parsing GenX result CSVs.

No Streamlit, no Julia. Runs under pytest, or standalone:

    python tests/test_metrics.py
"""
import sys
import tempfile
from pathlib import Path

_GENXUI = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_GENXUI))

from src import metrics  # noqa: E402


# ── synthetic result dirs ───────────────────────────────────────────────────

# 2 zones: gas (z1), solar (z1, some curtailment), battery (z1), wind (z2), and
# a ghost thermal in z2 with zero everything.
_CAP_MZ = (
    "Resource,Zone,StartCap,RetCap,NewCap,EndCap,EndEnergyCap,EndChargeCap\n"
    "z1_gas,1,0,0,100,100,0,0\n"
    "z1_solar,1,0,0,200,200,0,0\n"
    "z1_battery,1,0,0,50,50,150,0\n"
    "z2_wind,2,0,0,300,300,0,0\n"
    "z2_ghost,2,0,0,0,0,0,0\n"
    "Total,,0,0,650,650,150,0\n"
)
_POWER_MZ = (
    "Resource,z1_gas,z1_solar,z1_battery,z2_wind,z2_ghost\n"
    "Zone,1,1,1,2,2\n"
    "AnnualSum,1000,4000,500,6000,0\n"
    "t1,10,40,5,60,0\n"
    "t2,10,40,5,60,0\n"
)
_CURTAIL_MZ = (
    "Resource,z1_solar,z2_wind\n"
    "Zone,1,2\n"
    "AnnualSum,300,900\n"
    "t1,3,9\n"
)
_CHARGE_MZ = (
    "Resource,z1_battery\n"
    "Zone,1\n"
    "AnnualSum,600\n"
    "t1,6\n"
)
_NSE_MZ = (
    "Segment,1,1.1,Total\n"
    "Zone,1,2,0\n"
    "AnnualSum,120,80,200\n"
    "t1,1,0,1\n"
)
_PB_MZ = (
    "BalanceComponent,Demand,Nonserved_Energy,Demand.1,Nonserved_Energy.1\n"
    "Zone,1,1,2,2\n"
    "AnnualSum,-5000,120,-6000,80\n"
    "t1,-50,1,-60,0\n"
)
_COSTS_MZ = "Costs,Total,Zone1,Zone2\ncTotal,1000,600,400\ncFix,800,500,300\ncNSE,5,3,2\n"
_NETREV_MZ = (
    "region,Resource,zone,Inv_cost_MW,Fixed_OM_cost_MW,Var_OM_cost_out,Fuel_cost,StartCost,Cost\n"
    "z1,z1_gas,1,1e6,2e5,1e5,3e5,1e4,1.61e6\n"
    "z1,z1_solar,1,8e5,1e5,0,0,0,9e5\n"
    "z1,z1_battery,1,2e5,5e4,0,0,0,2.5e5\n"
    "z2,z2_wind,2,9e5,1e5,0,0,0,1e6\n"
    "z2,Total,0,0,0,0,0,0,0\n"
)


def _mk(tmp: Path, files: dict[str, str]) -> Path:
    for name, content in files.items():
        (tmp / name).write_text(content, encoding="utf-8")
    return tmp


def _mz(tmp: Path) -> Path:
    return _mk(tmp, {
        "capacity.csv": _CAP_MZ, "power.csv": _POWER_MZ, "curtailment.csv": _CURTAIL_MZ,
        "charge.csv": _CHARGE_MZ, "nse.csv": _NSE_MZ, "power_balance.csv": _PB_MZ,
        "costs.csv": _COSTS_MZ, "NetRevenue.csv": _NETREV_MZ,
    })


# ── load_results ────────────────────────────────────────────────────────────

def test_no_capacity_csv_returns_none():
    with tempfile.TemporaryDirectory() as t:
        assert metrics.load_results(Path(t)) is None


def test_zones_detected():
    with tempfile.TemporaryDirectory() as t:
        rs = metrics.load_results(_mz(Path(t)))
        assert rs.zones == [1, 2] and rs.multi_zone is True


def test_ghost_resource_dropped():
    with tempfile.TemporaryDirectory() as t:
        rs = metrics.load_results(_mz(Path(t)))
        assert rs.dropped_resources == ["z2_ghost"]
        assert "z2_ghost" not in metrics.capacity_by_resource(rs)["Resource"].tolist()


def test_missing_optional_csv_is_tolerated():
    with tempfile.TemporaryDirectory() as t:
        rs = metrics.load_results(_mk(Path(t), {"capacity.csv": _CAP_MZ}))
        assert rs is not None
        assert not metrics.capacity_by_resource(rs).empty
        assert metrics.generation_by_resource(rs)["AnnualGen_MWh"].sum() == 0.0
        assert metrics.nse_total_mwh(rs) == 0.0


# ── capacity / generation ──────────────────────────────────────────────────

def test_capacity_by_resource_types_and_zones():
    with tempfile.TemporaryDirectory() as t:
        rs = metrics.load_results(_mz(Path(t)))
        c = metrics.capacity_by_resource(rs).set_index("Resource")
        assert c.loc["z1_gas", "Type"] == "Thermal" and c.loc["z1_gas", "Zone"] == 1
        assert c.loc["z2_wind", "Type"] == "Wind" and c.loc["z2_wind", "Zone"] == 2
        assert c.loc["z1_battery", "EndEnergy_MWh"] == 150


def test_generation_from_power_csv():
    with tempfile.TemporaryDirectory() as t:
        rs = metrics.load_results(_mz(Path(t)))
        g = metrics.generation_by_resource(rs).set_index("Resource")["AnnualGen_MWh"]
        assert g["z2_wind"] == 6000 and g["z1_solar"] == 4000


# ── zone summary ───────────────────────────────────────────────────────────

def test_zone_summary_has_subtotals_and_total():
    with tempfile.TemporaryDirectory() as t:
        rs = metrics.load_results(_mz(Path(t)))
        zs = metrics.zone_summary(rs)
        assert zs["is_subtotal"].sum() == 2          # one per zone
        assert zs["is_total"].sum() == 1
        tot = zs[zs["is_total"]].iloc[0]
        assert tot["Capacity_MW"] == 650             # ghost excluded
        assert tot["Curtailment_MWh"] == 1200


def test_zone_summary_single_zone_has_no_subtotals():
    with tempfile.TemporaryDirectory() as t:
        rs = metrics.load_results(_mk(Path(t), {
            "capacity.csv": "Resource,Zone,EndCap,EndEnergyCap\nsolar,1,100,0\nTotal,,100,0\n",
            "power.csv": "Resource,solar\nZone,1\nAnnualSum,500\nt1,5\n",
        }))
        zs = metrics.zone_summary(rs)
        assert zs["is_subtotal"].sum() == 0 and zs["is_total"].sum() == 1


# ── supply to load ─────────────────────────────────────────────────────────

def test_supply_to_load_nets_vre_charging_and_adds_system_row():
    with tempfile.TemporaryDirectory() as t:
        rs = metrics.load_results(_mz(Path(t)))
        stl = metrics.supply_to_load(rs)
        assert "System" in stl["Zone"].astype(str).tolist()
        # z1 solar (4000 gen) is the only VRE in z1; battery charge 600 → gen-to-load 3400
        z1_solar = stl[(stl["Zone"] == 1) & (stl["Type"] == "Solar")]["GenToLoad_MWh"].iloc[0]
        assert abs(z1_solar - 3400) < 1e-6
        # battery discharge counts fully
        z1_stor = stl[(stl["Zone"] == 1) & (stl["Type"] == "Storage")]["GenToLoad_MWh"].iloc[0]
        assert abs(z1_stor - 500) < 1e-6


def test_supply_to_load_includes_unserved_energy():
    with tempfile.TemporaryDirectory() as t:
        rs = metrics.load_results(_mz(Path(t)))
        stl = metrics.supply_to_load(rs)
        u1 = stl[(stl["Zone"] == 1) & (stl["Type"] == "Unserved")]["GenToLoad_MWh"]
        u2 = stl[(stl["Zone"] == 2) & (stl["Type"] == "Unserved")]["GenToLoad_MWh"]
        assert u1.iloc[0] == 120 and u2.iloc[0] == 80
        usys = stl[(stl["Zone"] == "System") & (stl["Type"] == "Unserved")]["GenToLoad_MWh"]
        assert usys.iloc[0] == 200


# ── costs / nse / breakdown ────────────────────────────────────────────────

def test_costs_components():
    with tempfile.TemporaryDirectory() as t:
        rs = metrics.load_results(_mz(Path(t)))
        c = metrics.costs_components(rs)
        assert c["cTotal"] == 1000 and c["cNSE"] == 5


def test_nse_summary_and_total():
    with tempfile.TemporaryDirectory() as t:
        rs = metrics.load_results(_mz(Path(t)))
        assert metrics.nse_total_mwh(rs) == 200
        ns = metrics.nse_summary(rs).set_index("Zone")["NSE_MWh"]
        assert ns[1] == 120 and ns[2] == 80 and ns["System"] == 200


def test_cost_breakdown_columns():
    with tempfile.TemporaryDirectory() as t:
        rs = metrics.load_results(_mz(Path(t)))
        cb = metrics.cost_breakdown(rs).set_index("Resource")
        assert cb.loc["z1_gas", "Fuel"] == 0.3      # 3e5 / 1e6
        assert "z2_wind" in cb.index and "Total" not in cb.index


def test_asset_metrics_energy_and_cost_split():
    with tempfile.TemporaryDirectory() as t:
        rs = metrics.load_results(_mz(Path(t)))
        am = metrics.asset_metrics(rs).set_index("Resource")

        gas = am.loc["z1_gas"]
        # cost columns sum to the LCOE numerator (LCOE × dispatch)
        comp = gas[["CapExPower_$", "CapExEnergy_$", "OpEx_$", "Emissions_$", "ChargeCost_$"]].sum()
        assert abs(comp - gas["LCOE_$MWh"] * gas["AnnualGen_MWh"]) < 1e-3
        assert abs(gas["CapExPower_$"] - 1e6) < 1e-6           # Inv_cost_MW
        assert abs(gas["OpEx_$"] - (2e5 + 1e5 + 3e5 + 1e4)) < 1e-6  # FixedOM+VarOM+Fuel+Start

        batt = am.loc["z1_battery"]
        assert abs(batt["EnergyToCharge_MWh"] - 600) < 1e-6    # charge.csv AnnualSum
        assert batt["ChargeCost_$"] == 0.0                      # not in this NetRevenue fixture

        assert "z2_ghost" not in am.index
        full = metrics.asset_metrics(rs)
        tot = full[full["is_total"]].iloc[0]
        assert tot["Resource"] == "System"
        # System LCOE is cost / energy-served-to-load (option B basis)
        cost_cols = ["CapExPower_$", "CapExEnergy_$", "OpEx_$", "Emissions_$", "ChargeCost_$"]
        expect = full.loc[~full["is_total"], cost_cols].sum().sum() / \
            full.loc[~full["is_total"], "EnergyToLoad_MWh"].sum()
        assert abs(tot["LCOE_$MWh"] - expect) < 1e-6


# ── interzonal transfers / annual-output layout ────────────────────────────

# A DC-OPF-style run: generation in z1, load in z3, z2 a pure transit zone.
# Written in the long "WriteOutputs: annual" layout (no t1..tN rows).
_ANNUAL = {
    "capacity.csv": (
        "Resource,Zone,StartCap,RetCap,NewCap,EndCap,EndEnergyCap,EndChargeCap\n"
        "z1_gas,1,0,0,500,500,0,0\n"
        "Total,,0,0,500,500,0,0\n"
    ),
    "power.csv": "Resource,Zone,AnnualSum\nz1_gas,1,1000000\nTotal,0,1000000\n",
    "curtailment.csv": "Resource,Zone,AnnualSum\nz1_gas,1,0\nTotal,0,0\n",
    "nse.csv": (
        "Segment,Zone,AnnualSum\n1,1,0\n2,1,0\n1,2,0\n2,2,0\n1,3,0\n2,3,0\nTotal,0,0\n"
    ),
    "power_balance.csv": (
        "BalanceComponent,Zone,AnnualSum\n"
        "Generation,1,1000000\nNonserved_Energy,1,0\nTransmission_NetExport,1,-1000000\n"
        "Transmission_Losses,1,0\nDemand,1,0\n"
        "Generation,2,0\nNonserved_Energy,2,0\nTransmission_NetExport,2,0\n"
        "Transmission_Losses,2,0\nDemand,2,0\n"
        "Generation,3,0\nNonserved_Energy,3,0\nTransmission_NetExport,3,1000000\n"
        "Transmission_Losses,3,0\nDemand,3,-1000000\n"
    ),
}


def test_annual_layout_parses_generation_and_all_zones():
    with tempfile.TemporaryDirectory() as t:
        rs = metrics.load_results(_mk(Path(t), _ANNUAL))
        # power_balance.csv surfaces the load-only / transit zones capacity.csv omits
        assert rs.zones == [1, 2, 3]
        g = metrics.generation_by_resource(rs).set_index("Resource")["AnnualGen_MWh"]
        assert g["z1_gas"] == 1_000_000
        assert metrics.nse_total_mwh(rs) == 0.0


def test_zone_balance_roles_and_signs():
    with tempfile.TemporaryDirectory() as t:
        rs = metrics.load_results(_mk(Path(t), _ANNUAL))
        zb = metrics.zone_balance(rs).set_index("Zone")
        assert zb.loc[1, "Role"] == "Generation only"
        assert zb.loc[2, "Role"] == "Transit"
        assert zb.loc[3, "Role"] == "Load only"
        assert zb.loc[1, "NetImport_MWh"] == -1_000_000   # exporter
        assert zb.loc[3, "NetImport_MWh"] == 1_000_000     # importer
        assert zb.loc[3, "Demand_MWh"] == 1_000_000        # positive magnitude


def test_supply_to_load_attributes_imports_to_the_load_zone():
    with tempfile.TemporaryDirectory() as t:
        rs = metrics.load_results(_mk(Path(t), _ANNUAL))
        stl = metrics.supply_to_load(rs)
        # z1 generates but has no load → dropped from the per-zone mix
        assert stl[stl["Zone"] == 1].empty
        # z3's entire load shows up as Imports
        z3 = stl[stl["Zone"] == 3].set_index("Type")["GenToLoad_MWh"]
        assert list(z3.index) == ["Imports"] and abs(z3["Imports"] - 1_000_000) < 1.0
        # System row keeps the real fuel mix (no Imports slice)
        sys_types = set(stl[stl["Zone"] == "System"]["Type"])
        assert sys_types == {"Thermal"}


def test_supply_to_load_single_zone_unchanged_by_interzonal_logic():
    with tempfile.TemporaryDirectory() as t:
        rs = metrics.load_results(_mk(Path(t), {
            "capacity.csv": "Resource,Zone,EndCap,EndEnergyCap\ngas,1,100,0\nTotal,,100,0\n",
            "power.csv": "Resource,gas\nZone,1\nAnnualSum,500\nt1,5\n",
        }))
        stl = metrics.supply_to_load(rs)
        assert "System" not in stl["Zone"].astype(str).tolist()
        assert "Imports" not in stl["Type"].tolist()
        assert stl[stl["Type"] == "Thermal"]["GenToLoad_MWh"].iloc[0] == 500


# ── timeseries ─────────────────────────────────────────────────────────────

def test_timeseries_accessors_indexed_by_hour():
    with tempfile.TemporaryDirectory() as t:
        rs = metrics.load_results(_mz(Path(t)))
        ns = metrics.nse_timeseries(rs)
        assert list(ns.index) == [1] and ns.iloc[0] == 1
        pw = metrics.power_timeseries(rs)
        assert pw.index.name == "hour" and "z1_gas" in pw.columns


# ── standalone runner ──────────────────────────────────────────────────────

if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
