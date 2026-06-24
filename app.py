import subprocess
import threading
import queue
import time
from pathlib import Path
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

    st.link_button("📖 GenX Docs", "https://genxproject.github.io/GenX.jl/stable/", use_container_width=True)

    if st.button("Clear output", disabled=st.session_state.running):
        st.session_state.output_lines = []
        st.session_state.return_code = None
        st.rerun()

with col_terminal:
    st.subheader("Terminal output")

    def render_terminal():
        text = "".join(st.session_state.output_lines) or "No output yet."
        with st.container(height=600):
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
