"""Tests for src/fleet_view.py and src/resource_style.py.

No Streamlit, no Plotly. Runs under pytest, or standalone:

    python tests/test_fleet_view.py
"""
import sys
import tempfile
from pathlib import Path

_GENXUI = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_GENXUI))

from src import fleet_view as fv                         # noqa: E402
from src.resource_style import COLORS, resource_color    # noqa: E402


# ── fixtures ─────────────────────────────────────────────────────────────────

_THERMAL = (
    "Resource,Zone,Existing_Cap_MW,Max_Cap_MW,Min_Cap_MW,Inv_Cost_per_MWyr,New_Build,Can_Retire,region\n"
    "MA_natural_gas,1,0,-1,0,65400,1,0,MA\n"
    "CT_natural_gas,2,0,-1,0,65400,1,0,CT\n"
)
_VRE_FIXED = (
    "Resource,Zone,Existing_Cap_MW,Max_Cap_MW,Min_Cap_MW,Inv_Cost_per_MWyr,New_Build,Can_Retire,region\n"
    "CA_solar,1,400,400,0,85300,1,0,CA\n"
    "CA_wind,1,0,0,0,97200,0,1,CA\n"          # 0 MW but retireable -> still 'exists'
)
_WITH_PHANTOM = (
    "Resource,Zone,Existing_Cap_MW,Max_Cap_MW,New_Build,Can_Retire,region\n"
    "REAL_plant,1,100,100,0,0,CA\n"
    "GHOST_plant,1,0,0,0,0,CA\n"              # can't build, can't retire, 0 MW -> dropped
)
_NETWORK_LIST = (
    ",Network_zones,Network_Lines,Start_Zone,End_Zone,Line_Max_Flow_MW\n"
    "MA,z1,1,1,2,2950\n"
    "CT,z2,2,1,3,2000\n"
    "ME,z3,,,,\n"
)
_NETWORK_MATRIX = (
    "Network_Lines,z1,z2,z3\n"
    "1,1,-1,0\n"
    "2,1,0,-1\n"
)


def _case(tmp: Path, resources: dict[str, str], network: str | None = None) -> Path:
    (tmp / "resources").mkdir(parents=True)
    for fname, body in resources.items():
        (tmp / "resources" / fname).write_text(body, encoding="utf-8")
    if network is not None:
        (tmp / "system").mkdir()
        (tmp / "system" / "Network.csv").write_text(network, encoding="utf-8")
    return tmp


# ── load_fleet ──────────────────────────────────────────────────────────────

def test_load_fleet_parses_types_zones_and_sentinel():
    with tempfile.TemporaryDirectory() as t:
        c = _case(Path(t), {"Thermal.csv": _THERMAL, "Vre.csv": _VRE_FIXED})
        res = fv.load_fleet(c)
        assert len(res) == 4
        thermal = [r for r in res if r.type == "Thermal"]
        assert {r.zone for r in thermal} == {1, 2}
        assert all(r.max_mw is None for r in thermal)      # -1 -> None
        solar = next(r for r in res if r.name == "CA_solar")
        assert solar.type == "VRE" and solar.existing_mw == 400 and solar.max_mw == 400


def test_load_fleet_filename_filter():
    with tempfile.TemporaryDirectory() as t:
        c = _case(Path(t), {"Thermal.csv": _THERMAL, "Vre.csv": _VRE_FIXED})
        assert {r.type for r in fv.load_fleet(c, ["Vre.csv"])} == {"VRE"}


def test_load_fleet_no_resources_dir():
    with tempfile.TemporaryDirectory() as t:
        assert fv.load_fleet(Path(t)) == []


def test_load_fleet_drops_nonexistent_rows():
    with tempfile.TemporaryDirectory() as t:
        c = _case(Path(t), {"Thermal.csv": _WITH_PHANTOM})
        shown = fv.load_fleet(c)
        assert [r.name for r in shown] == ["REAL_plant"]
        assert len(fv.load_fleet(c, include_absent=True)) == 2


def test_fleetresource_exists_property():
    with tempfile.TemporaryDirectory() as t:
        c = _case(Path(t), {"Thermal.csv": _WITH_PHANTOM})
        by_name = {r.name: r for r in fv.load_fleet(c, include_absent=True)}
        assert by_name["REAL_plant"].exists is True
        assert by_name["GHOST_plant"].exists is False


# ── metrics ─────────────────────────────────────────────────────────────────

def test_metrics_greenfield():
    with tempfile.TemporaryDirectory() as t:
        c = _case(Path(t), {"Thermal.csv": _THERMAL})
        m = fv.fleet_metrics(fv.load_fleet(c))
        assert m["greenfield"] is True
        assert m["count"] == 2 and m["n_zones"] == 2
        assert m["existing_total_mw"] == 0
        assert m["candidate_count"] == 2
        assert m["by_type"] == {"Thermal": 2}


def test_metrics_fixed_fleet():
    with tempfile.TemporaryDirectory() as t:
        c = _case(Path(t), {"Vre.csv": _VRE_FIXED})
        m = fv.fleet_metrics(fv.load_fleet(c))
        assert m["greenfield"] is False
        assert m["existing_total_mw"] == 400
        assert m["candidate_count"] == 0        # solar has existing cap; wind isn't new_build


# ── sizing ──────────────────────────────────────────────────────────────────

def test_size_series_uniform_fallback_on_greenfield():
    with tempfile.TemporaryDirectory() as t:
        res = fv.load_fleet(_case(Path(t), {"Thermal.csv": _THERMAL}))
        vals, uniform, note = fv.size_series(res, "existing_mw")
        assert uniform is True and vals == [1.0, 1.0] and note and "greenfield" in note.lower()


def test_size_series_uses_real_values():
    with tempfile.TemporaryDirectory() as t:
        res = fv.load_fleet(_case(Path(t), {"Vre.csv": _VRE_FIXED}))
        vals, uniform, note = fv.size_series(res, "existing_mw")
        assert uniform is False and note is None and vals == [400.0, 0.0]


def test_size_series_inv_cost_path_for_greenfield():
    with tempfile.TemporaryDirectory() as t:
        res = fv.load_fleet(_case(Path(t), {"Thermal.csv": _THERMAL}))
        vals, uniform, _ = fv.size_series(res, "inv_cost")
        assert uniform is False and vals == [65400.0, 65400.0]


# ── frame ───────────────────────────────────────────────────────────────────

def test_fleet_frame_columns_and_unbounded_marker():
    with tempfile.TemporaryDirectory() as t:
        res = fv.load_fleet(_case(Path(t), {"Thermal.csv": _THERMAL}))
        df = fv.fleet_frame(res, [1.0, 1.0])
        assert {"Resource", "Type", "Zone", "Size", "Color", "New_Build"} <= set(df.columns)
        assert (df["Max_MW"] == "∞").all()


# ── network parsing ─────────────────────────────────────────────────────────

def test_read_network_list_interface():
    with tempfile.TemporaryDirectory() as t:
        c = _case(Path(t), {"Thermal.csv": _THERMAL}, network=_NETWORK_LIST)
        assert fv.read_network_lines(c) == [(1, 2), (1, 3)]


def test_read_network_matrix_interface():
    with tempfile.TemporaryDirectory() as t:
        c = _case(Path(t), {"Thermal.csv": _THERMAL}, network=_NETWORK_MATRIX)
        assert sorted(fv.read_network_lines(c)) == [(1, 2), (1, 3)]


def test_read_network_absent():
    with tempfile.TemporaryDirectory() as t:
        c = _case(Path(t), {"Thermal.csv": _THERMAL})
        assert fv.read_network_lines(c) == []


# ── bus layout ──────────────────────────────────────────────────────────────

def test_bus_layout_single_zone_central_hub():
    with tempfile.TemporaryDirectory() as t:
        res = fv.load_fleet(_case(Path(t), {"Vre.csv": _VRE_FIXED}))
        lay = fv.bus_layout(res)
        assert len(lay["hubs"]) == 1
        assert lay["hubs"][0]["x"] == 0.0 and lay["hubs"][0]["y"] == 0.0
        assert len(lay["nodes"]) == 2 and len(lay["spokes"]) == 2 and lay["ties"] == []


def test_bus_layout_multi_zone_with_ties():
    with tempfile.TemporaryDirectory() as t:
        res = fv.load_fleet(_case(Path(t), {"Thermal.csv": _THERMAL}))
        lay = fv.bus_layout(res, sizes=[10.0, 20.0], tie_lines=[(1, 2)])
        assert len(lay["hubs"]) == 2
        assert len(lay["nodes"]) == 2 and len(lay["spokes"]) == 2
        assert len(lay["ties"]) == 1
        assert {n["size"] for n in lay["nodes"]} == {10.0, 20.0}


def test_bus_layout_empty():
    lay = fv.bus_layout([])
    assert all(lay[k] == [] for k in ("hubs", "nodes", "spokes", "ties", "loads", "load_edges"))


def test_bus_layout_demand_adds_load_nodes():
    with tempfile.TemporaryDirectory() as t:
        res = fv.load_fleet(_case(Path(t), {"Thermal.csv": _THERMAL}))
        lay = fv.bus_layout(res, tie_lines=[(1, 2)], demand={1: 8000.0, 2: 3000.0})
        assert {ld["zone"]: ld["mw"] for ld in lay["loads"]} == {1: 8000.0, 2: 3000.0}
        assert len(lay["load_edges"]) == 2


def test_bus_layout_demand_only_zone_still_gets_a_hub():
    # a zone that has demand but no resources should still appear
    lay = fv.bus_layout([], demand={5: 1200.0})
    assert [h["zone"] for h in lay["hubs"]] == [5]
    assert lay["loads"][0]["mw"] == 1200.0


# ── zone demand ─────────────────────────────────────────────────────────────

_DEMAND = (
    "Voll,Demand_Segment,Time_Index,Demand_MW_z1,Demand_MW_z2\n"
    "50000,1,1,7850,2242\n"
    ",2,2,9100,2000\n"
    ",,3,8000,2500\n"
)


def test_read_zone_demand_peaks():
    with tempfile.TemporaryDirectory() as t:
        c = Path(t)
        (c / "system").mkdir()
        (c / "system" / "Demand_data.csv").write_text(_DEMAND, encoding="utf-8")
        assert fv.read_zone_demand(c) == {1: 9100.0, 2: 2500.0}


def test_read_zone_demand_absent():
    with tempfile.TemporaryDirectory() as t:
        assert fv.read_zone_demand(Path(t)) == {}


# ── colours ─────────────────────────────────────────────────────────────────

def test_resource_color_keywords():
    assert resource_color("MA_natural_gas_combined_cycle") == COLORS["thermal"]
    assert resource_color("CA_solar_pv") == COLORS["solar"]
    assert resource_color("CT_onshore_wind") == COLORS["wind"]
    assert resource_color("MA_battery") == COLORS["storage"]
    assert resource_color("something_else") == COLORS["other"]


# ── standalone runner ────────────────────────────────────────────────────────

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
