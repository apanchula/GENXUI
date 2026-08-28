"""Tests for src/run_preview.build_run_preview().

No Streamlit, no Julia. Runs under pytest, or standalone:

    python tests/test_run_preview.py
"""
import sys
import tempfile
from pathlib import Path

_GENXUI = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_GENXUI))

from src.run_preview import build_run_preview  # noqa: E402


# ── builders ────────────────────────────────────────────────────────────────

def _mk(tmp: Path, *, genx: str = "", tdr_yml: str = "", tdr_files: dict | None = None,
        demand_rows: int = 48, sys_demand_extra_cols: str = "",
        policies: dict | None = None, resources: dict | None = None,
        network: str | None = None) -> Path:
    (tmp / "settings").mkdir(parents=True)
    (tmp / "settings" / "genx_settings.yml").write_text(genx, encoding="utf-8")
    if tdr_yml:
        (tmp / "settings" / "time_domain_reduction_settings.yml").write_text(tdr_yml, encoding="utf-8")

    (tmp / "system").mkdir()
    hdr = "Time_Index,Demand_MW_z1" + sys_demand_extra_cols
    body = "\n".join(f"{i},{100 + i}" + ",0" * sys_demand_extra_cols.count(",")
                     for i in range(1, demand_rows + 1))
    (tmp / "system" / "Demand_data.csv").write_text(hdr + "\n" + body + "\n", encoding="utf-8")
    if network is not None:
        (tmp / "system" / "Network.csv").write_text(network, encoding="utf-8")

    if tdr_files is not None:
        (tmp / "TDR_results").mkdir()
        for name, content in tdr_files.items():
            (tmp / "TDR_results" / name).write_text(content, encoding="utf-8")

    (tmp / "resources").mkdir()
    for name, content in (resources or {}).items():
        (tmp / "resources" / name).write_text(content, encoding="utf-8")

    (tmp / "policies").mkdir()
    for name, content in (policies or {}).items():
        (tmp / "policies" / name).write_text(content, encoding="utf-8")
    return tmp


_TDR_CLUSTERED_DEMAND = (
    "Rep_Periods,Timesteps_per_Rep_Period,Time_Index,Demand_MW_z1\n"
    "11,168,1,500\n" + "\n".join(f",,{i},500" for i in range(2, 1849)) + "\n"
)
_TDR_TRIPLE = {
    "Demand_data.csv": _TDR_CLUSTERED_DEMAND,
    "Generators_variability.csv": "Time_Index,x\n1,0\n",
    "Fuels_data.csv": "Time_Index,x\n1,0\n",
}


# ── timesteps ───────────────────────────────────────────────────────────────

def test_tdr_off_by_default():
    with tempfile.TemporaryDirectory() as t:
        pv = build_run_preview(_mk(Path(t), genx="UCommit: 0\n", demand_rows=48))
        assert pv.timesteps == 48
        assert "no reduction" in pv.timesteps_basis
        assert any("defaults to" in w for w in pv.warnings)


def test_tdr_reusing_existing_folder():
    with tempfile.TemporaryDirectory() as t:
        pv = build_run_preview(_mk(Path(t), genx="TimeDomainReduction: 1\n",
                                   tdr_files=_TDR_TRIPLE))
        assert pv.timesteps == 1848
        assert "reusing" in pv.timesteps_basis and "11 representative periods" in pv.timesteps_basis


def test_tdr_will_cluster_shows_range():
    with tempfile.TemporaryDirectory() as t:
        pv = build_run_preview(_mk(
            Path(t), genx="TimeDomainReduction: 1\n",
            tdr_yml="TimestepsPerRepPeriod: 168\nMinPeriods: 8\nMaxPeriods: 11\n"
                    "IterativelyAddPeriods: 1\nThreshold: 0.05\n",
        ))
        assert pv.timesteps is None
        assert "1,344–1,848" in pv.timesteps_basis and "5% error" in pv.timesteps_basis


def test_tdr_folder_ignored_when_flag_off():
    with tempfile.TemporaryDirectory() as t:
        pv = build_run_preview(_mk(Path(t), genx="UCommit: 0\n", tdr_files=_TDR_TRIPLE))
        assert pv.timesteps == 48
        assert any("will be ignored" in w for w in pv.warnings)


def test_tdr_partial_folder_warns_and_reclusters():
    with tempfile.TemporaryDirectory() as t:
        partial = {"Demand_data.csv": _TDR_CLUSTERED_DEMAND}  # missing the other two
        pv = build_run_preview(_mk(
            Path(t), genx="TimeDomainReduction: 1\n", tdr_files=partial,
            tdr_yml="TimestepsPerRepPeriod: 168\nMinPeriods: 8\nMaxPeriods: 11\n",
        ))
        assert pv.timesteps is None
        assert any("incomplete" in w for w in pv.warnings)


def test_already_clustered_system_input_warns():
    with tempfile.TemporaryDirectory() as t:
        c = _mk(Path(t), genx="TimeDomainReduction: 1\n",
                tdr_yml="TimestepsPerRepPeriod: 168\nMinPeriods: 8\nMaxPeriods: 11\n")
        (c / "system" / "Demand_data.csv").write_text(
            "Rep_Periods,Time_Index,Demand_MW_z1\n4,1,500\n,2,500\n", encoding="utf-8")
        pv = build_run_preview(c)
        assert any("already looks clustered" in w for w in pv.warnings)


# ── rows ────────────────────────────────────────────────────────────────────

def _row(pv, label):
    return next((r for r in pv.rows if r.label == label), None)


def test_co2_cap_row_counts_zonal_caps():
    with tempfile.TemporaryDirectory() as t:
        pv = build_run_preview(_mk(
            Path(t), genx="CO2Cap: 2\n",
            policies={"CO2_cap.csv": "x,CO_2_Cap_Zone_1,CO_2_Cap_Zone_2,CO_2_Cap_Zone_3\n"
                                    "a,1,0,0\n"},
        ))
        r = _row(pv, "CO₂ cap")
        assert r.value == "rate-based (demand)" and "3 zonal cap(s)" in r.hint


def test_defaults_are_all_off():
    with tempfile.TemporaryDirectory() as t:
        pv = build_run_preview(_mk(Path(t), genx=""))
        assert _row(pv, "CO₂ cap").value == "off"
        assert _row(pv, "Unit commitment").value == "off"
        assert _row(pv, "Network expansion").value == "off"
        assert _row(pv, "Other policies").value == "none"
        assert pv.error is None


def test_zones_and_resources_rows():
    with tempfile.TemporaryDirectory() as t:
        pv = build_run_preview(_mk(
            Path(t), genx="",
            network="x,Network_zones,Start_Zone,End_Zone\nMA,z1,1,2\nCT,z2,,\n",
            resources={"Thermal.csv": "Resource,Zone\ngas1,1\ngas2,2\n",
                       "Vre.csv": "Resource,Zone\nsolar,1\n"},
        ))
        assert _row(pv, "Zones").value == "2"
        rr = _row(pv, "Resources")
        assert rr.value == "3" and "Thermal: 2" in rr.hint and "VRE: 1" in rr.hint


# ── errors ──────────────────────────────────────────────────────────────────

def test_missing_demand_data_is_an_error_not_a_crash():
    with tempfile.TemporaryDirectory() as t:
        c = Path(t)
        (c / "settings").mkdir(parents=True)
        (c / "settings" / "genx_settings.yml").write_text("", encoding="utf-8")
        (c / "system").mkdir()
        pv = build_run_preview(c)
        assert pv.error is not None and pv.timesteps is None


def test_nonexistent_case_path_is_handled():
    pv = build_run_preview(Path("/no/such/case/anywhere"))
    assert pv.error is not None


# ── real bundled example systems ────────────────────────────────────────────

def test_real_example_systems_have_no_error():
    root = _GENXUI.parent / "GenX.jl" / "example_systems"
    if not root.exists():
        return
    checked = 0
    for case in sorted(root.iterdir()):
        if not (case / "settings" / "genx_settings.yml").exists():
            continue
        pv = build_run_preview(case)
        assert pv.error is None, f"{case.name}: {pv.error}"
        assert pv.timesteps_basis
        checked += 1
    assert checked >= 5


# ── standalone runner ───────────────────────────────────────────────────────

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
