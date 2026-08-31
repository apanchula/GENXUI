"""Tests for the GENXUI-6 case-management helpers in src/workspace.py and the
`dest_name` argument on src/examples.import_example_case.

No Streamlit. Runs under pytest, or standalone:

    python tests/test_workspace_cases.py
"""
import sys
import tempfile
from pathlib import Path

_GENXUI = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_GENXUI))

from src import workspace  # noqa: E402


def _ws(tmp: Path) -> Path:
    workspace.set_workspace_root(tmp)
    return workspace.data_dir()


def _case(data: Path, name: str, *, with_results: bool = True) -> Path:
    c = data / name
    (c / "settings").mkdir(parents=True)
    (c / "settings" / "genx_settings.yml").write_text("UCommit: 0\n", encoding="utf-8")
    (c / "resources").mkdir()
    (c / "resources" / "Thermal.csv").write_text("Resource\ngas\n", encoding="utf-8")
    (c / "Run.jl").write_text("using GenX\n", encoding="utf-8")
    if with_results:
        (c / "results").mkdir()
        (c / "results" / "costs.csv").write_text("x\n1\n", encoding="utf-8")
        (c / "TDR_results").mkdir()
        (c / "TDR_results" / "Demand_data.csv").write_text("x\n1\n", encoding="utf-8")
    return c


# ── valid_case_name ────────────────────────────────────────────────────────

def test_valid_case_name_accepts():
    for n, expect in [("base_case", "base_case"), ("  spaced  ", "spaced"),
                      ("a b c", "a b c"), ("scenario-1.2", "scenario-1.2"),
                      ("case.", "case")]:
        assert workspace.valid_case_name(n) == expect


def test_valid_case_name_rejects():
    for n in ["", "   ", ".", "..", "a/b", "a\\b", 'a"b', "a:b", "a*b",
              "CON", "com1", "NUL", "\tx"]:
        assert workspace.valid_case_name(n) is None


# ── rename_case ────────────────────────────────────────────────────────────

def test_rename_moves_whole_folder():
    with tempfile.TemporaryDirectory() as t:
        data = _ws(Path(t))
        _case(data, "c1")
        dest = workspace.rename_case("c1", "c2")
        assert dest == data / "c2"
        assert not (data / "c1").exists()
        assert (dest / "results" / "costs.csv").exists()      # results ride along
        assert (dest / "Run.jl").exists()
        assert workspace.discover_cases() == ["c2"]


def test_rename_errors():
    with tempfile.TemporaryDirectory() as t:
        data = _ws(Path(t))
        _case(data, "c1")
        _case(data, "c2")
        try:
            workspace.rename_case("nope", "x"); assert False
        except FileNotFoundError:
            pass
        try:
            workspace.rename_case("c1", "CON"); assert False
        except ValueError:
            pass
        try:
            workspace.rename_case("c1", "c2"); assert False
        except FileExistsError:
            pass
        assert sorted(workspace.discover_cases()) == ["c1", "c2"]   # nothing moved


# ── duplicate_case ─────────────────────────────────────────────────────────

def test_duplicate_full():
    with tempfile.TemporaryDirectory() as t:
        data = _ws(Path(t))
        _case(data, "c1")
        d = workspace.duplicate_case("c1", "c1_full")
        assert (d / "results" / "costs.csv").exists()
        assert (d / "TDR_results").exists()
        assert (data / "c1").exists()                          # source untouched


def test_duplicate_inputs_only():
    with tempfile.TemporaryDirectory() as t:
        data = _ws(Path(t))
        _case(data, "c1")
        d = workspace.duplicate_case("c1", "c1_io", inputs_only=True)
        assert (d / "settings" / "genx_settings.yml").exists()
        assert (d / "resources" / "Thermal.csv").exists()
        assert (d / "Run.jl").exists()
        assert not (d / "results").exists()
        assert not (d / "TDR_results").exists()


def test_duplicate_bad_name():
    with tempfile.TemporaryDirectory() as t:
        data = _ws(Path(t))
        _case(data, "c1")
        try:
            workspace.duplicate_case("c1", "a/b"); assert False
        except ValueError:
            pass


# ── delete_case ────────────────────────────────────────────────────────────

def test_delete_removes_only_the_data_folder():
    with tempfile.TemporaryDirectory() as t:
        data = _ws(Path(t))
        _case(data, "c1")
        archive = workspace.archive_dir()
        (archive / "c1__old").mkdir()
        workspace.delete_case("c1")
        assert not (data / "c1").exists()
        assert (archive / "c1__old").exists()                  # archive untouched
        try:
            workspace.delete_case("c1"); assert False
        except FileNotFoundError:
            pass


# ── examples.import_example_case(dest_name=…) ──────────────────────────────

def test_import_example_with_dest_name(monkeypatch):
    from src import examples
    with tempfile.TemporaryDirectory() as t:
        data = _ws(Path(t))
        fake_examples = Path(t) / "ex"
        (fake_examples / "1_toy" / "settings").mkdir(parents=True)
        (fake_examples / "1_toy" / "Run.jl").write_text("using GenX\n", encoding="utf-8")
        (fake_examples / "1_toy" / "README.md").write_text("A toy case.\n", encoding="utf-8")
        monkeypatch.setattr(examples, "_examples_root", lambda: fake_examples)

        dest = examples.import_example_case("1_toy", dest_name="my scenario")
        assert dest == data / "my scenario"
        assert (dest / "Run.jl").exists()
        try:
            examples.import_example_case("1_toy", dest_name="my scenario"); assert False
        except FileExistsError:
            pass
        try:
            examples.import_example_case("1_toy", dest_name="a/b"); assert False
        except ValueError:
            pass


# ── standalone runner ──────────────────────────────────────────────────────

if __name__ == "__main__":
    class _MP:
        def setattr(self, obj, name, val):
            setattr(obj, name, val)

    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn(_MP()) if fn.__code__.co_argcount else fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
