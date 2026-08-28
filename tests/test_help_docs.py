"""Tests for src/help_docs.py — parsing the bundled GenX docs snapshot.

No Streamlit, no network. Runs under pytest, or standalone:

    python tests/test_help_docs.py
"""
import sys
from pathlib import Path

_GENXUI = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_GENXUI))

from src import help_docs  # noqa: E402


# ── settings_help ────────────────────────────────────────────────────────────

def test_ucommit_lists_all_three_modes():
    ph = help_docs.settings_help("UCommit")
    assert ph is not None
    blob = ph.as_markdown().lower()
    assert "no unit commitment" in blob
    assert "integer clustering" in blob
    assert "linearized clustering" in blob


def test_timedomainreduction_mentions_reuse_and_off():
    ph = help_docs.settings_help("TimeDomainReduction")
    assert ph is not None
    blob = ph.as_markdown().lower()
    assert "timedomainreductionfolder" in blob        # folder-reuse behaviour
    assert "do not perform clustering" in blob         # the 0 default


def test_co2cap_enumerates_four_modes():
    ph = help_docs.settings_help("CO2Cap")
    assert ph is not None
    assert len(ph.values) == 4
    assert "mass-based" in ph.as_markdown().lower()


def test_case_insensitive_fallback():
    assert help_docs.settings_help("ucommit") is not None


def test_unknown_key_returns_none():
    assert help_docs.settings_help("NotARealSetting") is None


def test_tdr_settings_key_resolves():
    # keys from time_domain_reduction_settings.yml also live in the index
    assert help_docs.settings_help("MaxPeriods") is not None


def test_solver_settings_keys_resolve():
    # keys from gurobi_settings.yml / clp_settings.yml / highs_settings.yml
    for k in ("Method", "Feasib_Tol", "Pre_Solve", "TimeLimit", "MIPGap"):
        ph = help_docs.settings_help(k)
        assert ph is not None, k
    # the cross-solver Method row carries the per-solver parameter names
    assert "gurobi" in help_docs.settings_help("Method").as_markdown().lower()


def test_solver_topic_available():
    assert any(t.slug == "solver" and t.available for t in help_docs.topics())


# ── column_help ──────────────────────────────────────────────────────────────

def test_resource_common_column_via_fallback():
    # Min_Cap_MW is in the "common to all resources" table, not Thermal's own
    h = help_docs.column_help("Thermal", "Min_Cap_MW")
    assert h and "discharge capacity" in h.lower()


def test_thermal_specific_column():
    h = help_docs.column_help("Thermal.csv", "Cap_size")
    assert h and "mw" in h.lower()


def test_policy_column_with_numeric_suffix_wildcard():
    # doc column is CO_2_Cap_Zone_*  → must match CO_2_Cap_Zone_1
    h = help_docs.column_help("CO2_cap", "CO_2_Cap_Zone_1")
    assert h and "eligible" in h.lower()


def test_min_cap_requirement_column():
    h = help_docs.column_help("Minimum_capacity_requirement", "Min_MW")
    assert h and "mw" in h.lower()


def test_output_column_has_units():
    h = help_docs.column_help("capacity", "EndCap")
    assert h and "(MW)" in h


def test_unknown_column_returns_none():
    assert help_docs.column_help("Thermal", "NotAColumn") is None


def test_documented_columns_preserves_order_and_filters():
    cols = ["Resource", "NotAColumn", "Zone", "Min_Cap_MW"]
    got = [c for c, _ in help_docs.documented_columns("Vre", cols)]
    assert got == ["Resource", "Zone", "Min_Cap_MW"]


# ── topics / body / search ───────────────────────────────────────────────────

def test_all_topics_available_from_bundle():
    assert help_docs.topics()
    assert all(t.available for t in help_docs.topics())


def test_topic_body_is_cleaned():
    body = help_docs.topic_body("intro")
    assert "```@raw" not in body and "<ol>" not in body and "](@ref" not in body


def test_topic_body_unknown_slug():
    assert "not available" in help_docs.topic_body("nope").lower()


def test_search_time_domain_returns_tdr_first():
    hits = help_docs.search("time domain reduction")
    assert hits and hits[0].topic_slug == "tdr"


def test_search_co2_cap_surfaces_the_policy_section():
    hits = help_docs.search("co2 cap")
    assert any("co2_cap.csv" in h.section.lower() or "co2" in h.section.lower()
               for h in hits[:3])


def test_search_empty_query():
    assert help_docs.search("") == []


# ── live-checkout preference ─────────────────────────────────────────────────

def test_prefers_live_checkout_when_present(tmp_path, monkeypatch):
    live_dir = tmp_path / "GenX.jl" / "docs" / "src" / "User_Guide"
    live_dir.mkdir(parents=True)
    (live_dir / "model_configuration.md").write_text(
        "|**Parameter** | **Description**|\n| :-- | :-- |\n|UCommit | SENTINEL LIVE VALUE|\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(help_docs.workspace, "legacy_genx_root", lambda: tmp_path / "GenX.jl")
    help_docs._kv_index.cache_clear()
    try:
        ph = help_docs.settings_help("UCommit")
        assert ph and "SENTINEL LIVE VALUE" in ph.summary
    finally:
        help_docs._kv_index.cache_clear()


# ── standalone runner ────────────────────────────────────────────────────────

if __name__ == "__main__":
    import types

    class _MP:
        def setattr(self, obj, name, val):
            setattr(obj, name, val)

    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            n = fn.__code__.co_argcount
            if n == 2:
                import tempfile
                with tempfile.TemporaryDirectory() as td:
                    fn(Path(td), _MP())
            else:
                fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
