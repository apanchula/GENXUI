"""Tests for src/run_diagnosis.diagnose().

Pure functions — no Streamlit, no Julia. Runs under pytest, or standalone:

    python tests/test_run_diagnosis.py
"""
import sys
from pathlib import Path

_GENXUI = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_GENXUI))

from src.run_diagnosis import diagnose  # noqa: E402

_TRANSCRIPTS = Path(__file__).parent / "transcripts"


# ── Signature matching ───────────────────────────────────────────────────────

def test_bad_alloc_is_oom():
    txt = ("Running HiPO\n[33272] signal 22: SIGABRT\n"
           "terminate called after throwing an instance of 'std::bad_alloc'\n"
           "  what():  std::bad_alloc\n")
    assert diagnose(txt, 3).signature_id == "out_of_memory"


def test_windows_paging_file_is_oom():
    txt = ("ERROR: LoadError: Error opening package file "
           "C:\\Users\\x\\.julia\\compiled\\v1.12\\DataFrames\\AR9oZ.dll: "
           "The paging file is too small for this operation to complete.\n")
    assert diagnose(txt, 1).signature_id == "out_of_memory"


def test_julia_outofmemoryerror_is_oom():
    assert diagnose("ERROR: LoadError: OutOfMemoryError()\n", 1).signature_id == "out_of_memory"


def test_oom_beats_generic_julia_error():
    # bad_alloc runs also print ERROR:/LoadError lines — OOM must win by order.
    txt = "ERROR: LoadError: something\nstd::bad_alloc\n"
    assert diagnose(txt, 3).signature_id == "out_of_memory"


def test_infeasible():
    assert diagnose("Model status        : Infeasible\n", 1).signature_id == "model_infeasible"


def test_unbounded():
    assert diagnose("Model status        : Unbounded\n", 1).signature_id == "model_unbounded"


def test_time_limit():
    assert diagnose("HiGHS: Time limit reached\n", 1).signature_id == "solver_time_limit"


def test_missing_input_file():
    txt = "ERROR: LoadError: SystemError: opening file \"Demand_data.csv\": No such file or directory\n"
    assert diagnose(txt, 1).signature_id in {"missing_input_file", "julia_load_error"}
    # missing_input_file is above julia_load_error in the catalog, so it wins:
    assert diagnose(txt, 1).signature_id == "missing_input_file"


def test_package_resolution():
    txt = "ERROR: LoadError: ArgumentError: Package GenX not found in current path.\n"
    assert diagnose(txt, 1).signature_id == "package_resolution"


def test_julia_not_found():
    assert diagnose("ERROR: 'julia' not found on PATH.\n", 127).signature_id == "julia_not_found"


def test_generic_julia_error_fallback():
    txt = "ERROR: LoadError: MethodError: no method matching foo(::Int)\n"
    assert diagnose(txt, 1).signature_id == "julia_load_error"


# ── Return-code semantics ────────────────────────────────────────────────────

def test_clean_success_has_no_diagnosis():
    assert diagnose("Writing Output!\nAll done.\n", 0) is None


def test_success_with_scaling_warning():
    txt = "WARNING: Problem has some excessively large costs\nWriting Output!\n"
    d = diagnose(txt, 0)
    assert d is not None and d.signature_id == "objective_scaling" and d.severity == "warning"


def test_error_signature_suppressed_on_clean_exit():
    # A stray 'error:' in otherwise-fine output must not raise a false alarm.
    assert diagnose("note: no error: found here\nWriting Output!\n", 0) is None


def test_unknown_nonzero_is_generic():
    assert diagnose("something weird happened\n", 5).signature_id == "unknown_failure"


def test_diagnosis_fields_are_populated():
    d = diagnose("std::bad_alloc\n", 3)
    assert d.title and d.detail and d.remedy
    assert d.docs_url  # out_of_memory carries a docs link


# ── Captured real transcripts ────────────────────────────────────────────────

def test_captured_transcripts():
    """Each tests/transcripts/<id>__rc<N>.log must diagnose to <id>."""
    if not _TRANSCRIPTS.exists():
        return
    logs = sorted(_TRANSCRIPTS.glob("*.log"))
    assert logs, "transcripts/ exists but is empty"
    for log in logs:
        stem = log.stem                      # e.g. out_of_memory__rc3
        expected_id, _, rc_part = stem.partition("__rc")
        rc = int(rc_part)
        got = diagnose(log.read_text(encoding="utf-8", errors="replace"), rc)
        got_id = got.signature_id if got else None
        assert got_id == expected_id, f"{log.name}: expected {expected_id}, got {got_id}"


# ── Standalone runner ────────────────────────────────────────────────────────

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
