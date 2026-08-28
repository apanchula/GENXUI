import subprocess
import threading
import queue
import time
from pathlib import Path
import pandas as pd
import streamlit as st

import archive_lib
from src import examples, run_diagnosis, run_settings, workspace

st.set_page_config(page_title="GenX UI", layout="wide")

# ── Workspace setup gate ────────────────────────────────────────────────────
# The workspace root is unset by default on first run. If unset, show a setup
# prompt requiring the user to choose a directory before any case list loads —
# the app must not crash and must not silently fall back to scanning
# `../GenX.jl` (GENXUI-1).


def _render_workspace_setup(*, changing: bool = False):
    st.title("GenX UI")
    if changing:
        st.subheader("Change workspace")
    else:
        st.subheader("Set up your workspace")
        st.info(
            "GenXUI needs one workspace folder to work from. It will contain a "
            "`data/` directory for active cases and an `archive/` directory for "
            "saved runs."
        )

    default = str(workspace.get_workspace_root() or Path.home() / "genxui-workspace")
    root_input = st.text_input("Workspace folder", value=default, key="workspace_root_input")

    if st.button("✅ Use this folder", type="primary"):
        try:
            workspace.set_workspace_root(Path(root_input))
            st.session_state.pop("_ws_cases_cache", None)
            st.toast(f"Workspace set to `{root_input}`", icon="✅")
            st.rerun()
        except OSError as e:
            st.error(f"Couldn't set up that folder: {e}")


_workspace_root = workspace.get_workspace_root()
if _workspace_root is None:
    _render_workspace_setup()
    st.stop()

GENX_ROOT = workspace.legacy_genx_root()  # GenX.jl solver checkout, used only for git-commit tracking on archive

CASES = workspace.discover_cases()

# ── Session state defaults ────────────────────────────────────────────────────
for key, default in {
    "running": False,
    "output_lines": [],
    "return_code": None,
    "run_diagnosis": None,
    "start_time": None,
    "elapsed_time": None,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default


def stream_process(case_path: Path, output_queue: queue.Queue):
    """Run Julia in a thread, pushing raw output lines into the queue, then a
    ("done", returncode) sentinel. Failure interpretation happens afterwards in
    run_diagnosis.diagnose() — the streamed output is left verbatim."""
    try:
        proc = subprocess.Popen(
            ["julia", "--project=.", "Run.jl"],
            cwd=str(case_path),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        for line in proc.stdout:
            output_queue.put(("line", line))
        proc.wait()
        output_queue.put(("done", proc.returncode))
    except FileNotFoundError:
        output_queue.put(("line", "ERROR: 'julia' not found on PATH.\n"))
        output_queue.put(("done", 127))


# ── System summary helpers ────────────────────────────────────────────────────
_RESOURCE_FILES = {
    "Thermal.csv":  "Thermal",
    "Vre.csv":      "VRE",
    "Storage.csv":  "Storage",
    "Vre_stor.csv": "VRE+Storage",
}


@st.cache_data
def _build_summary(cache_key: str) -> pd.DataFrame:
    res_dir = Path(cache_key.split("|")[0])
    rows = []

    for fname, rtype in _RESOURCE_FILES.items():
        fp = res_dir / fname
        if not fp.exists():
            continue
        df = pd.read_csv(fp).dropna(how="all")
        if df.empty:
            continue

        for _, r in df.iterrows():
            if pd.isnull(r.get("Resource")):
                continue

            max_cap = r.get("Max_Cap_MW", -1)
            new_build = r.get("New_Build", 0)

            row = {
                "Resource":           r["Resource"],
                "Type":               rtype,
                "New Build":          "Yes" if int(new_build) == 1 else "No",
                "Max Cap (MW)":       "∞" if float(max_cap) < 0 else f"{float(max_cap):,.1f}",
                "Inv ($/MW-yr)":      float(r.get("Inv_Cost_per_MWyr", 0) or 0),
                "Inv ($/MWh-yr)":     float(r["Inv_Cost_per_MWhyr"]) if rtype in ("Storage", "VRE+Storage") and "Inv_Cost_per_MWhyr" in r.index else None,
                "Fixed O&M ($/MW-yr)": float(r.get("Fixed_OM_Cost_per_MWyr", 0) or 0),
                "Var O&M ($/MWh)":    float(r.get("Var_OM_Cost_per_MWh", 0) or 0),
                "Notes":              "",
            }

            if rtype == "Thermal":
                hr   = r.get("Heat_Rate_MMBTU_per_MWh", "")
                fuel = r.get("Fuel", "")
                row["Notes"] = f"{hr} MMBtu/MWh · {fuel}"

            elif rtype == "Storage":
                eff_up   = float(r.get("Eff_Up",   1.0) or 1.0)
                eff_down = float(r.get("Eff_Down",  1.0) or 1.0)
                max_dur  = r.get("Max_Duration", "")
                row["Notes"] = f"RT {eff_up * eff_down:.0%} · {max_dur}h max"

            elif rtype == "VRE+Storage":
                row["Notes"] = "DC-coupled hybrid"

            rows.append(row)

    return pd.DataFrame(rows)


def load_system_summary(case_path: Path) -> pd.DataFrame | None:
    res_dir = case_path / "resources"
    if not res_dir.exists():
        return None
    csvs = list(res_dir.glob("*.csv"))
    if not csvs:
        return None
    mtime = str(max(f.stat().st_mtime for f in csvs))
    df = _build_summary(f"{res_dir}|{mtime}")
    return df if not df.empty else None


# ── Sidebar: workspace controller ───────────────────────────────────────────
with st.sidebar:
    st.subheader("Workspace")
    st.caption(f"`{workspace.get_workspace_root()}`")

    if workspace.has_unmigrated_legacy_archives() and not st.session_state.get("_legacy_notice_dismissed"):
        with st.container(border=True):
            st.caption(
                "ℹ️ Archived runs were found at the old default location "
                f"(`{workspace.legacy_archive_root()}`), outside your current workspace. "
                "They're not lost, just not shown here — set your workspace to that "
                "folder to see them, or leave them where they are."
            )
            if st.button("Dismiss", key="_dismiss_legacy_notice"):
                st.session_state["_legacy_notice_dismissed"] = True
                st.rerun()

    with st.expander("⚙️ Change workspace"):
        _render_workspace_setup(changing=True)

    with st.expander("📥 Import case from GenX.jl checkout"):
        _legacy_cases = workspace.list_legacy_cases()
        if not _legacy_cases:
            st.caption(f"No cases found under `{workspace.legacy_genx_root()}`.")
        else:
            _import_choice = st.selectbox("Case", _legacy_cases, key="_import_case_select")
            if st.button("Import into active workspace", key="_import_case_btn"):
                try:
                    dest = workspace.import_case_from_legacy(_import_choice)
                    st.success(f"Imported to `{dest.name}`")
                    st.rerun()
                except (FileNotFoundError, FileExistsError, OSError) as e:
                    st.error(str(e))

    with st.expander("🧪 Load GenX.jl example"):
        _example_cases = examples.list_example_cases()
        if not _example_cases:
            st.caption(f"No examples found under `{workspace.legacy_genx_root() / examples.EXAMPLES_DIRNAME}`.")
        else:
            _example_names = [c.name for c in _example_cases]
            _example_choice = st.selectbox("Example", _example_names, key="_example_case_select")
            _selected_example = next(c for c in _example_cases if c.name == _example_choice)
            if _selected_example.description:
                st.caption(_selected_example.description)
            if st.button("Load into active workspace", key="_example_case_btn"):
                try:
                    dest = examples.import_example_case(_example_choice)
                    st.success(f"Loaded to `{dest.name}`")
                    st.rerun()
                except (FileNotFoundError, FileExistsError, OSError) as e:
                    st.error(str(e))

    st.divider()
    st.link_button("📖 GenX Docs", "https://genxproject.github.io/GenX.jl/stable/", width="stretch")


# ── Layout ────────────────────────────────────────────────────────────────────
st.title("GenX Runner")

if not CASES:
    st.info(
        f"No cases found in your active workspace (`{workspace.data_dir()}`). "
        "Use **Import case from GenX.jl** in the sidebar to bring one in."
    )
    st.stop()

col_controls, col_terminal = st.columns([1, 2])

with col_controls:
    st.subheader("Case")

    if "app_case_select" not in st.session_state:
        _initial = st.session_state.get("selected_case")
        st.session_state["app_case_select"] = _initial if _initial in CASES else CASES[0]

    _preselect_case = st.session_state.pop("_preselect_case", None)
    if _preselect_case in CASES:
        st.session_state["app_case_select"] = _preselect_case

    case_name = st.selectbox("Select case", CASES, key="app_case_select")
    case_path = workspace.data_dir() / case_name

    st.caption(f"`{archive_lib.short_path(case_path, workspace.data_dir())}`")

    if st.button("📌 Set as default case", width="stretch"):
        st.session_state["selected_case"] = case_name
        st.toast(f"Default case set to **{case_name}** for Inputs and Results pages", icon="📌")

    _default_case = st.session_state.get("selected_case")
    if _default_case:
        st.caption(f"Default for Inputs/Results pages: **{_default_case}**")

    st.divider()

    run_btn = st.button(
        "▶  Run GenX",
        disabled=st.session_state.running,
        type="primary",
        width="stretch",
    )
    st.caption("Runs overwrite this case's `results/`. Use **📦 Archive this run** to keep a copy.")

    _rc = st.session_state.return_code
    if _rc is not None and not st.session_state.running:
        _diag = st.session_state.run_diagnosis

        if _diag is not None:
            _box = st.error if _diag.severity == "error" else st.warning
            _box(f"**{_diag.title}**\n\n{_diag.detail}")
            st.info(f"**Try this:** {_diag.remedy}")
            if _diag.docs_url:
                st.link_button("GenX docs", _diag.docs_url, width="stretch")
            st.caption(f"Exit code {_rc} · {_diag.signature_id}")

        if _rc == 0 and (_diag is None or _diag.severity == "warning"):
            st.success(f"Completed in {st.session_state.elapsed_time:.0f}s")
            archive_label = st.text_input("Archive label (optional)", key="runner_archive_label")
            if st.button("📦 Archive this run", width="stretch"):
                try:
                    archive_dir = archive_lib.create_archive(case_path, GENX_ROOT, label=archive_label)
                    st.success(f"Archived to `{archive_dir.name}`")
                except archive_lib.ArchiveError as e:
                    st.error(str(e))
        elif _rc != 0 and _diag is None:
            st.error(f"Failed (exit code {_rc})")

    if st.session_state.running:
        elapsed = time.time() - st.session_state.start_time
        st.info(f"Running… {elapsed:.0f}s")

    if st.button("Clear output", disabled=st.session_state.running):
        st.session_state.output_lines = []
        st.session_state.return_code = None
        st.session_state.run_diagnosis = None
        st.session_state.elapsed_time = None
        st.rerun()

with col_terminal:
    # ── System summary ────────────────────────────────────────────────────────
    summary = load_system_summary(case_path)
    if summary is not None:
        st.subheader("System Resources")
        st.dataframe(
            summary,
            hide_index=True,
            width="stretch",
            column_config={
                "Inv ($/MW-yr)":       st.column_config.NumberColumn(format="$%d"),
                "Inv ($/MWh-yr)":      st.column_config.NumberColumn(format="$%d"),
                "Fixed O&M ($/MW-yr)": st.column_config.NumberColumn(format="$%d"),
                "Var O&M ($/MWh)":     st.column_config.NumberColumn(format="$%.2f"),
            },
        )
        st.divider()

    # ── Terminal output ───────────────────────────────────────────────────────
    st.subheader("Terminal output")

    def render_terminal():
        text = "".join(st.session_state.output_lines) or "No output yet."
        with st.container(height=400):
            st.code(text, language=None)

    render_terminal()


# ── Launch run ────────────────────────────────────────────────────────────────
if run_btn:
    # GenXUI runs overwrite results/ rather than spilling to results_1/, _2/…
    # (history is kept via "Archive this run", not GenX's folder fan-out).
    _ovw = run_settings.ensure_overwrite_results(case_path)
    if _ovw:
        st.toast(f"Set `OverwriteResults: 1` for `{case_name}` — runs now overwrite "
                 "`results/`. Use “Archive this run” to keep copies.", icon="⚙️")

    st.session_state.running = True
    st.session_state.output_lines = []
    st.session_state.return_code = None
    st.session_state.run_diagnosis = None
    st.session_state.start_time = time.time()
    st.session_state.elapsed_time = None

    q = queue.Queue()
    t = threading.Thread(target=stream_process, args=(case_path, q), daemon=True)
    t.start()
    st.session_state["_queue"] = q
    st.session_state["_thread"] = t
    st.rerun()


# ── Poll queue while running ──────────────────────────────────────────────────
if st.session_state.running:
    q = st.session_state.get("_queue")
    if q:
        new_lines = False
        while not q.empty():
            kind, payload = q.get_nowait()
            if kind == "line":
                st.session_state.output_lines.append(payload)
                new_lines = True
            elif kind == "done":
                st.session_state.return_code = payload
                st.session_state.running = False
                st.session_state.elapsed_time = time.time() - st.session_state.start_time
                st.session_state.run_diagnosis = run_diagnosis.diagnose(
                    "".join(st.session_state.output_lines), payload
                )

        if st.session_state.running:
            time.sleep(0.25)
        st.rerun()
