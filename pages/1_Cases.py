"""Case management — create from example, rename, duplicate, delete (GENXUI-6)."""
import streamlit as st
from pathlib import Path

import archive_lib
from src import examples, ui, workspace

st.set_page_config(page_title="GenX – Cases", layout="wide")
ui.compact_layout()

if workspace.get_workspace_root() is None:
    st.title("Cases")
    st.info("No workspace configured yet. Set one up from the **Runner** page first.")
    st.stop()

st.title("Cases")
st.caption(f"Workspace `{workspace.get_workspace_root()}`")

_data = workspace.data_dir()
_cases = workspace.discover_cases()
_active = st.session_state.get("selected_case")


# ── helpers ─────────────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def _case_stat(case_str: str, sig: float) -> tuple[str, str]:
    del sig
    p = Path(case_str)
    total = 0
    newest_input = 0.0
    for f in p.rglob("*"):
        if not f.is_file():
            continue
        try:
            total += f.stat().st_size
        except OSError:
            continue
        rel = f.relative_to(p).parts
        if rel and rel[0] in ("resources", "system", "policies", "settings") or f.suffix == ".jl":
            newest_input = max(newest_input, f.stat().st_mtime)

    size = (f"{total / 1e6:,.0f} MB" if total >= 1e6
            else f"{total / 1e3:,.0f} kB" if total else "empty")

    rdir = workspace.resolve_results_dir(p)
    if rdir is None:
        status = "no results"
    elif newest_input and rdir.stat().st_mtime < newest_input:
        status = "⚠ results older than inputs"
    else:
        status = "has results"
    return size, status


def _dir_sig(p: Path) -> float:
    try:
        return max((f.stat().st_mtime for f in p.glob("**/*")), default=0.0)
    except OSError:
        return 0.0


def _run(fn, *args, ok: str, **kw):
    """Call a workspace mutation, surface the outcome, rerun on success."""
    try:
        fn(*args, **kw)
        st.toast(ok, icon="✅")
        return True
    except (FileNotFoundError, FileExistsError, ValueError, OSError) as e:
        st.error(str(e))
        return False


# ── new case from example ──────────────────────────────────────────────────
with st.container(border=True):
    st.markdown("**New case from a GenX.jl example**")
    _ex = examples.list_example_cases()
    if not _ex:
        st.caption(
            f"No examples found under `{workspace.legacy_genx_root() / examples.EXAMPLES_DIRNAME}`."
        )
    else:
        def _sync_case_name():
            # keep the name box defaulted to the picked example until the user
            # types their own name
            st.session_state["new_case_name"] = st.session_state["example_pick"]

        c1, c2, c3 = st.columns([3, 3, 1], vertical_alignment="bottom")
        _pick = c1.selectbox("Example", [e.name for e in _ex], key="example_pick",
                             on_change=_sync_case_name)
        _sel = next(e for e in _ex if e.name == _pick)
        st.session_state.setdefault("new_case_name", _pick)
        _name = c2.text_input("New case name", key="new_case_name")
        if c3.button("Create", type="primary", width="stretch"):
            if _run(examples.import_example_case, _pick, _name,
                    ok=f"Created case '{_name}'"):
                st.session_state["_preselect_case"] = workspace.valid_case_name(_name)
                st.session_state.pop("new_case_name", None)
                st.rerun()
        if _sel.description:
            st.caption(_sel.description)

st.divider()

if not _cases:
    st.info("No cases in the workspace yet — create one from an example above.")
    st.stop()

# ── existing cases ─────────────────────────────────────────────────────────
for name in _cases:
    cpath = workspace.case_dir(name)
    is_active = name == _active
    size, status = _case_stat(str(cpath), _dir_sig(cpath))

    with st.container(border=True):
        head, act = st.columns([4, 1])
        head.markdown(f"### {'▶ ' if is_active else ''}{name}")
        head.caption(
            f"`{archive_lib.short_path(cpath, _data)}` · {size} · {status}"
            + ("  ·  **active**" if is_active else "")
        )
        if not is_active and act.button("Set active", key=f"act_{name}", width="stretch"):
            st.session_state["selected_case"] = name
            st.rerun()

        p_ren, p_dup, p_del = st.columns(3)

        with p_ren.popover("✏️ Rename", width="stretch"):
            _new = st.text_input("New name", value=name, key=f"ren_{name}")
            if st.button("Rename", key=f"renbtn_{name}", type="primary"):
                if _run(workspace.rename_case, name, _new, ok=f"Renamed to '{_new}'"):
                    if is_active:
                        st.session_state["selected_case"] = workspace.valid_case_name(_new)
                    st.rerun()

        with p_dup.popover("📑 Duplicate", width="stretch"):
            _dname = st.text_input("Copy name", value=f"{name}_copy", key=f"dup_{name}")
            _io = st.checkbox("Inputs only (drop results / TDR_results)", value=True,
                              key=f"dupio_{name}")
            if st.button("Duplicate", key=f"dupbtn_{name}", type="primary"):
                if _run(workspace.duplicate_case, name, _dname, inputs_only=_io,
                        ok=f"Duplicated to '{_dname}'"):
                    st.rerun()

        with p_del.popover("🗑 Delete", width="stretch"):
            st.caption(f"Permanently delete **{name}** and its results. "
                       "Archived runs are not affected. This cannot be undone.")
            _confirm = st.text_input("Type `Delete` to confirm", key=f"del_{name}")
            if st.button("Delete case", key=f"delbtn_{name}", type="primary",
                         disabled=_confirm != "Delete"):
                if _run(workspace.delete_case, name, ok=f"Deleted '{name}'"):
                    if is_active:
                        st.session_state.pop("selected_case", None)
                    st.rerun()
