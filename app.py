import subprocess
import threading
import queue
import time
from pathlib import Path
import pandas as pd
import streamlit as st

st.set_page_config(page_title="GenX UI", layout="wide")

GENX_ROOT = Path(__file__).parent.parent / "GenX.jl"

CASES = sorted([
    d.name for d in GENX_ROOT.iterdir()
    if d.is_dir() and (d / "Run.jl").exists()
])

# ── Session state defaults ────────────────────────────────────────────────────
for key, default in {
    "running": False,
    "output_lines": [],
    "return_code": None,
    "start_time": None,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default


def stream_process(case_path: Path, output_queue: queue.Queue):
    """Run Julia in a thread, pushing output lines into the queue."""
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
        output_queue.put(("done", 1))


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
                "Max Cap (MW)":       "∞" if float(max_cap) < 0 else float(max_cap),
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


# ── Layout ────────────────────────────────────────────────────────────────────
st.title("GenX Runner")

col_controls, col_terminal = st.columns([1, 2])

with col_controls:
    st.subheader("Case")
    case_name = st.selectbox("Select case", CASES)
    case_path = GENX_ROOT / case_name

    st.caption(f"`{case_path}`")
    st.divider()

    run_btn = st.button(
        "▶  Run GenX",
        disabled=st.session_state.running,
        type="primary",
        width="stretch",
    )

    if st.session_state.return_code is not None and not st.session_state.running:
        if st.session_state.return_code == 0:
            elapsed = time.time() - st.session_state.start_time
            st.success(f"Completed in {elapsed:.0f}s")
        else:
            st.error(f"Failed (exit code {st.session_state.return_code})")

    if st.session_state.running:
        elapsed = time.time() - st.session_state.start_time
        st.info(f"Running… {elapsed:.0f}s")

    st.link_button("📖 GenX Docs", "https://genxproject.github.io/GenX.jl/stable/", width="stretch")

    if st.button("Clear output", disabled=st.session_state.running):
        st.session_state.output_lines = []
        st.session_state.return_code = None
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
    st.session_state.running = True
    st.session_state.output_lines = []
    st.session_state.return_code = None
    st.session_state.start_time = time.time()

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

        if st.session_state.running:
            time.sleep(0.25)
        st.rerun()
