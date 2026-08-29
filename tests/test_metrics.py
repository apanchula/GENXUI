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


def test_lcoe_by_resource():
    with tempfile.TemporaryDirectory() as t:
        rs = metrics.load_results(_mz(Path(t)))
        lc = metrics.lcoe_by_resource(rs)
        row = lc.set_index("Resource").loc["z1_gas"]
        # Cost 1.61e6 / dispatch 1000 MWh
        assert abs(row["LCOE_$MWh"] - 1610.0) < 1e-6
        assert row["is_total"] is False or row["is_total"] == False  # noqa: E712
        tot = lc[lc["is_total"]].iloc[0]
        assert tot["Resource"] == "TOTAL" and tot["LCOE_$MWh"] is not None
        # ghost resource excluded
        assert "z2_ghost" not in lc["Resource"].tolist()


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
