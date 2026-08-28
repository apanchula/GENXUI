"""Tests for workspace.resolve_results_dir() and run_settings.ensure_overwrite_results().

Pure filesystem logic — no Streamlit, no Julia. Runs under pytest, or standalone:

    python tests/test_results_resolution.py
"""
import os
import sys
import tempfile
import time
from pathlib import Path

_GENXUI = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_GENXUI))

from src.run_settings import ensure_overwrite_results  # noqa: E402
from src.workspace import resolve_results_dir           # noqa: E402


def _case(tmp: Path) -> Path:
    c = tmp / "1_three_zones"
    (c / "settings").mkdir(parents=True)
    return c


def _results(case: Path, name: str, *, age_s: float = 0.0) -> Path:
    d = case / name
    d.mkdir()
    (d / "costs.csv").write_text("x\n", encoding="utf-8")
    if age_s:
        old = time.time() - age_s
        os.utime(d, (old, old))
    return d


# ── resolve_results_dir ──────────────────────────────────────────────────────

def test_none_when_no_results():
    with tempfile.TemporaryDirectory() as t:
        assert resolve_results_dir(_case(Path(t))) is None


def test_plain_results_only():
    with tempfile.TemporaryDirectory() as t:
        c = _case(Path(t))
        r = _results(c, "results")
        assert resolve_results_dir(c) == r


def test_empty_results_ignored():
    with tempfile.TemporaryDirectory() as t:
        c = _case(Path(t))
        (c / "results").mkdir()          # empty
        r1 = _results(c, "results_1")
        assert resolve_results_dir(c) == r1


def test_newest_wins_fanout_scenario():
    # Old results/ from a first run, fresh results_1/ from a rerun.
    with tempfile.TemporaryDirectory() as t:
        c = _case(Path(t))
        _results(c, "results", age_s=1000)
        r1 = _results(c, "results_1")
        assert resolve_results_dir(c) == r1


def test_fresh_plain_results_beats_stale_results_1():
    # After the OverwriteResults fix: results/ overwritten in place, stale results_1/ left behind.
    with tempfile.TemporaryDirectory() as t:
        c = _case(Path(t))
        _results(c, "results_1", age_s=1000)
        r = _results(c, "results")
        assert resolve_results_dir(c) == r


def test_highest_suffix_breaks_mtime_tie():
    with tempfile.TemporaryDirectory() as t:
        c = _case(Path(t))
        same = time.time() - 500
        for name in ("results", "results_1", "results_2"):
            d = _results(c, name)
            os.utime(d, (same, same))
        assert resolve_results_dir(c).name == "results_2"


def test_non_numeric_suffix_ignored():
    with tempfile.TemporaryDirectory() as t:
        c = _case(Path(t))
        r = _results(c, "results")
        _results(c, "results_backup")   # not results_<N>
        assert resolve_results_dir(c) == r


# ── ensure_overwrite_results ─────────────────────────────────────────────────

_SETTINGS_WITH_KEY_0 = (
    "NetworkExpansion: 1 # transmission\n"
    "OverwriteResults: 0 # keep every run\n"
    "TimeDomainReduction: 1 # cluster\n"
)
_SETTINGS_NO_KEY = (
    "NetworkExpansion: 1 # transmission\n"
    "TimeDomainReduction: 1 # cluster\n"
)


def _write_settings(case: Path, text: str):
    (case / "settings" / "genx_settings.yml").write_text(text, encoding="utf-8")


def test_changes_zero_to_one_and_keeps_other_lines():
    with tempfile.TemporaryDirectory() as t:
        c = _case(Path(t))
        _write_settings(c, _SETTINGS_WITH_KEY_0)
        assert ensure_overwrite_results(c) == "changed"
        out = (c / "settings" / "genx_settings.yml").read_text(encoding="utf-8")
        assert "OverwriteResults: 1" in out
        assert "OverwriteResults: 0" not in out
        assert "NetworkExpansion: 1 # transmission" in out       # untouched
        assert "TimeDomainReduction: 1 # cluster" in out         # untouched
        assert out.endswith("\n")


def test_preserves_existing_inline_comment_on_change():
    with tempfile.TemporaryDirectory() as t:
        c = _case(Path(t))
        _write_settings(c, _SETTINGS_WITH_KEY_0)
        ensure_overwrite_results(c)
        line = next(l for l in (c / "settings" / "genx_settings.yml")
                    .read_text(encoding="utf-8").splitlines()
                    if l.startswith("OverwriteResults"))
        assert line == "OverwriteResults: 1 # keep every run"


def test_appends_key_when_absent():
    with tempfile.TemporaryDirectory() as t:
        c = _case(Path(t))
        _write_settings(c, _SETTINGS_NO_KEY)
        assert ensure_overwrite_results(c) == "added"
        out = (c / "settings" / "genx_settings.yml").read_text(encoding="utf-8")
        assert out.count("OverwriteResults: 1") == 1
        assert "set by GenXUI" in out
        assert out.endswith("\n")


def test_idempotent_when_already_one():
    with tempfile.TemporaryDirectory() as t:
        c = _case(Path(t))
        _write_settings(c, _SETTINGS_NO_KEY)
        assert ensure_overwrite_results(c) == "added"
        assert ensure_overwrite_results(c) is None
        assert ensure_overwrite_results(c) is None


def test_none_when_no_settings_file():
    with tempfile.TemporaryDirectory() as t:
        assert ensure_overwrite_results(_case(Path(t))) is None


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
