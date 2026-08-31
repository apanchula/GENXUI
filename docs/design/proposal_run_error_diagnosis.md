<!-- status: implemented 2026-08-28 · owner: GenXUI · created 2026-08-28 -->
<!-- shipped in src/run_diagnosis.py + app.py; tests in tests/test_run_diagnosis.py -->
<!-- deviations from the sketch below: exit code for missing julia is 127 (not 1);
     added an objective_scaling warning-severity signature; the OOM catalog also
     matches Julia OutOfMemoryError and a bare "out of memory". -->


# Proposal: Run error diagnosis & user-facing messaging

## Problem

When a GenX run fails, the UI tells the user almost nothing:

```
Failed (exit code 3)
```

The real explanation is somewhere in the 400-line terminal pane, in Julia /
HiGHS wording the user is not expected to parse. Concretely, the case that
prompted this:

```
[33272] signal 22: SIGABRT
terminate called after throwing an instance of 'std::bad_alloc'
  what():  std::bad_alloc
```

That is the machine running out of memory during the HiGHS solve. The user
should see:

> **Ran out of memory.** The solver could not allocate enough RAM to solve this
> case on this machine. Close other applications and run it again.

Today's code has exactly one bespoke check — `_is_package_resolution_failure()`
in [`app.py`](../app.py) — which appends a banner *line* into the terminal
blob. It does not generalise, it is not surfaced as a real status, and it is
mixed into `stream_process()` where it can't be unit-tested.

## Goals

- Turn a failed run into a **structured diagnosis**: a headline, a plain-language
  explanation, and a concrete "try this" remedy.
- Render it as a real status callout, not a line lost in the scrollback.
- Keep the raw terminal output **completely untouched** — it is still the source
  of truth for support.
- Make the failure catalog **data**, so new signatures are a one-line addition
  with a test, not a new branch in `stream_process()`.
- Cover the success-with-warnings case too (e.g. objective scaling warnings).

## Non-goals

- Parsing GenX results or model economics — this is purely about run health.
- Retrying or auto-fixing (e.g. auto-switching HiGHS `Method`). The remedy text
  may *suggest* a fix; applying it stays the user's call.
- A RAM pre-flight check (see [Future](#future-work)).

---

## Design

### New module: `src/run_diagnosis.py`

Self-contained, no Streamlit import, fully unit-testable.

```python
"""Post-mortem diagnosis of a GenX run from its combined stdout+stderr.

stream_process() in app.py merges stderr into stdout, so the entire run
transcript is available as one string. After the Julia process exits we run
that transcript (plus the return code) through an ordered catalog of failure
signatures and surface the first match as a RunDiagnosis the UI can render.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Literal

Severity = Literal["error", "warning"]


@dataclass(frozen=True)
class RunDiagnosis:
    signature_id: str          # stable id, for telemetry / tests
    severity: Severity
    title: str                 # short headline, no trailing period
    detail: str                # 1-2 sentences: what happened, in plain terms
    remedy: str                # concrete next action for the user
    docs_url: str | None = None


@dataclass(frozen=True)
class _Signature:
    id: str
    severity: Severity
    title: str
    detail: str
    remedy: str
    # match(transcript_lower, returncode) -> bool
    match: Callable[[str, int], bool]
    docs_url: str | None = None


def _has(*needles: str) -> Callable[[str, int], bool]:
    """All needles present somewhere in the (lower-cased) transcript."""
    needles = tuple(n.lower() for n in needles)
    return lambda text, rc: all(n in text for n in needles)


def _any(*needles: str) -> Callable[[str, int], bool]:
    needles = tuple(n.lower() for n in needles)
    return lambda text, rc: any(n in text for n in needles)
```

### The catalog

Ordered **most specific first**. `diagnose()` returns the first signature whose
`match` is true; `None` means "no signature matched" (the UI then shows a
generic failure with the exit code).

```python
_CATALOG: list[_Signature] = [

    _Signature(
        id="julia_not_found",
        severity="error",
        title="Julia isn't available",
        detail="The 'julia' command could not be found on this system's PATH.",
        remedy="Install Julia (https://julialang.org/downloads) and make sure "
               "`julia --version` works in a normal terminal, then retry.",
        match=lambda text, rc: "'julia' not found on path" in text,
    ),

    _Signature(
        id="out_of_memory",
        severity="error",
        title="Ran out of memory",
        detail="The solver could not allocate enough RAM to build or solve this "
               "case on this machine. Larger cases (full-year hourly, many "
               "resources, electrolyzers, multi-stage) need substantially more "
               "memory.",
        remedy="Close other applications to free up memory and run it again. "
               "If it still fails, try a smaller case, or set the solver "
               "`Method` to `simplex` in the case's settings/highs_settings.yml "
               "(interior-point uses far more memory).",
        match=_any(
            "std::bad_alloc",                       # HiGHS / C++ allocation
            "outofmemoryerror",                     # Julia
            "the paging file is too small",         # Windows, during precompile
            "error opening package file",           # Windows precompile OOM tell
            "cannot allocate memory",               # Linux
            "killed",                               # Linux OOM killer (with rc 137)
        ),
        docs_url="https://genxproject.github.io/GenX.jl/stable/",
    ),

    _Signature(
        id="model_infeasible",
        severity="error",
        title="No feasible solution",
        detail="The optimization problem has no solution that satisfies all "
               "constraints — usually a policy constraint (CO2 cap, capacity "
               "reserve margin, min/max capacity) that can't be met by the "
               "available resources.",
        remedy="Relax or disable the binding policy in settings/genx_settings.yml, "
               "add capacity headroom, or enable the policy's slack variables "
               "(see the 4_three_zones_w_policies_slack example).",
        match=_any("model status        : infeasible", "primal infeasible",
                   "is infeasible", "infeasibility"),
    ),

    _Signature(
        id="model_unbounded",
        severity="error",
        title="Model is unbounded",
        detail="The objective can be improved without limit — typically a "
               "missing upper bound or a negative-cost resource with no cap.",
        remedy="Check for resources with zero or negative cost and no "
               "Max_Cap_MW, and confirm demand / policy inputs loaded correctly.",
        match=_any("model status        : unbounded", "primal unbounded"),
    ),

    _Signature(
        id="solver_time_limit",
        severity="error",
        title="Solver hit its time limit",
        detail="HiGHS stopped before converging because it reached the "
               "configured time limit.",
        remedy="Raise TimeLimit in settings/highs_settings.yml, reduce the "
               "model size (time-domain reduction, fewer resources), or switch "
               "solver Method.",
        match=_any("time limit reached", "reached time limit"),
    ),

    _Signature(
        id="missing_input_file",
        severity="error",
        title="An input file is missing or misnamed",
        detail="GenX or Julia could not open a required input CSV/YAML for this "
               "case.",
        remedy="Compare this case's folder against a known-good example — check "
               "the settings/ files and the resources/ and system/ CSVs exist "
               "and are named exactly as GenX expects.",
        match=_any("systemerror", "no such file or directory",
                   "could not find", "isadirectoryerror"),
    ),

    _Signature(
        id="package_resolution",
        severity="error",
        title="GenX package could not be loaded",
        detail="Julia could not resolve the GenX package (or one of its "
               "dependencies) from this environment. This is an environment "
               "problem, not a model error.",
        remedy="Confirm GenX is installed in your default Julia environment "
               "(`julia -e 'using Pkg; Pkg.status()'` should list GenX), or add "
               "a Project.toml to the case that depends on GenX.",
        match=_has("argumenterror", "not found"),
    ),

    _Signature(
        id="julia_load_error",
        severity="error",
        title="The run crashed with a Julia error",
        detail="Julia raised an unhandled error while running the case. The "
               "specific message is in the terminal output above.",
        remedy="Read the first `ERROR:` line in the terminal output — it names "
               "the actual problem. If it's about your inputs, fix those; "
               "otherwise capture the full output for a bug report.",
        match=_any("error: loaderror", "\nerror:"),
    ),
]
```

### The entry point

```python
_GENERIC_FAIL = RunDiagnosis(
    signature_id="unknown_failure",
    severity="error",
    title="The run failed",
    detail="GenX exited with a non-zero status but no known failure pattern "
           "was recognised in its output.",
    remedy="Scan the terminal output for the first `ERROR:` or `WARNING:` "
           "line. If you can't tell what went wrong, capture the full output "
           "for a bug report.",
)


def diagnose(transcript: str, returncode: int) -> RunDiagnosis | None:
    """Return a RunDiagnosis for a finished run, or None if it succeeded cleanly.

    - returncode 0 and no warning signature  -> None
    - returncode 0 with a warning signature  -> warning-severity RunDiagnosis
    - returncode != 0                        -> first matching signature,
                                                else _GENERIC_FAIL
    """
    text = transcript.lower()

    for sig in _CATALOG:
        if sig.match(text, returncode):
            # A warning signature only fires as advice on an otherwise-OK run;
            # on a hard failure a more specific error signature should win.
            if returncode == 0 and sig.severity != "warning":
                continue
            return RunDiagnosis(
                signature_id=sig.id, severity=sig.severity, title=sig.title,
                detail=sig.detail, remedy=sig.remedy, docs_url=sig.docs_url,
            )

    if returncode != 0:
        return _GENERIC_FAIL
    return None
```

(Warning-severity signatures — e.g. an `objective_scaling` entry keyed on
`"excessively large costs"` — slot into the same catalog; they're the only ones
allowed to fire when `returncode == 0`.)

---

## Wiring into `app.py`

### `stream_process()` — stop injecting banner lines

Remove `_is_package_resolution_failure()` and the mid-stream `package_failure`
banner. `stream_process()` goes back to doing one thing: stream raw lines, then
signal completion.

```python
def stream_process(case_path: Path, output_queue: queue.Queue):
    try:
        proc = subprocess.Popen(
            ["julia", "--project=.", "Run.jl"],
            cwd=str(case_path),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
        for line in proc.stdout:
            output_queue.put(("line", line))
        proc.wait()
        output_queue.put(("done", proc.returncode))
    except FileNotFoundError:
        output_queue.put(("line", "ERROR: 'julia' not found on PATH.\n"))
        output_queue.put(("done", 127))
```

The invocation and `cwd` are unchanged.

### Queue-drain handler — run diagnosis on `done`

```python
elif kind == "done":
    st.session_state.return_code = payload
    st.session_state.running = False
    st.session_state.elapsed_time = time.time() - st.session_state.start_time
    st.session_state.run_diagnosis = run_diagnosis.diagnose(
        "".join(st.session_state.output_lines), payload
    )
```

Add `"run_diagnosis": None` to the session-state defaults, and clear it in the
run-launch block and "Clear output" handler alongside `return_code`.

### `col_controls` — render the diagnosis

Replace:

```python
        else:
            st.error(f"Failed (exit code {st.session_state.return_code})")
```

with:

```python
    diag = st.session_state.get("run_diagnosis")
    rc = st.session_state.return_code
    if rc is not None and not st.session_state.running:
        if rc == 0 and diag is None:
            st.success(f"Completed in {st.session_state.elapsed_time:.0f}s")
            # ... existing archive controls ...
        elif diag is not None:
            box = st.error if diag.severity == "error" else st.warning
            box(f"**{diag.title}**\n\n{diag.detail}")
            st.info(f"**Try this:** {diag.remedy}")
            if diag.docs_url:
                st.link_button("GenX docs", diag.docs_url, width="stretch")
            st.caption(f"Exit code {rc} · {diag.signature_id}")
            if rc == 0:                       # warning on a successful run
                st.success(f"Completed in {st.session_state.elapsed_time:.0f}s")
                # ... existing archive controls ...
        else:
            st.error(f"Failed (exit code {rc})")
```

The `signature_id` in the caption is deliberately visible — it makes bug
reports precise ("I got `out_of_memory`") without the user quoting a stack
trace.

---

## Rendering rules

| Situation | Shown |
|---|---|
| rc 0, no warning signature | green "Completed in Ns" + archive controls (unchanged) |
| rc 0, warning signature | yellow callout + "Try this" + green success + archive controls |
| rc ≠ 0, signature matched | red callout + "Try this" + optional docs link + `exit code · id` caption |
| rc ≠ 0, nothing matched | red generic callout pointing at the terminal + exit code |

The terminal pane is never modified — every byte Julia emitted is still there,
verbatim, for support.

---

## Testing

`tests/test_run_diagnosis.py` — pure functions, no Streamlit, no Julia:

```python
def test_bad_alloc_is_oom():
    d = diagnose("... terminate called ... std::bad_alloc\n  what():  std::bad_alloc\n", 3)
    assert d.signature_id == "out_of_memory"

def test_windows_paging_file_is_oom():
    d = diagnose("Error opening package file ...: The paging file is too small", 1)
    assert d.signature_id == "out_of_memory"

def test_infeasible():
    assert diagnose("Model status        : Infeasible", 1).signature_id == "model_infeasible"

def test_package_resolution():
    d = diagnose("ERROR: LoadError: ArgumentError: Package GenX not found in current path.", 1)
    assert d.signature_id == "package_resolution"

def test_oom_beats_generic_julia_error():
    # bad_alloc also prints 'ERROR:' lines — OOM must win by catalog order
    txt = "ERROR: LoadError: ...\nstd::bad_alloc\n"
    assert diagnose(txt, 3).signature_id == "out_of_memory"

def test_clean_success_has_no_diagnosis():
    assert diagnose("All done\nWriting Output!\n", 0) is None

def test_unknown_nonzero_is_generic():
    assert diagnose("something weird\n", 5).signature_id == "unknown_failure"
```

Keep a folder of **real captured transcripts** (`tests/transcripts/*.log`,
scrubbed of absolute paths) and assert each maps to the right `signature_id` —
that's the regression net when a GenX or HiGHS version changes its wording.

---

## Adding a signature

1. Append one `_Signature(...)` to `_CATALOG`, positioned by specificity
   (specific failures above generic ones; `julia_load_error` stays last).
2. Add a captured transcript to `tests/transcripts/` and a one-line assertion.
3. If it's advice for an otherwise-successful run, set `severity="warning"`.

No changes to `app.py` or `stream_process()`.

---

## Future work

- **RAM pre-flight.** Before launching, compare available memory
  (`psutil.virtual_memory().available`) against a rough per-case estimate
  (scale from time-series length × resource count) and warn *before* a
  20-minute build that's going to `bad_alloc`. Needs `psutil` as a dependency
  and some calibration; out of scope here.
- **Signature-driven quick actions.** e.g. the `out_of_memory` remedy could
  offer a one-click "set this case's HiGHS Method to simplex" button. Deferred
  on purpose — diagnosis first, automation later.
- **Telemetry.** Log `signature_id` + case + elapsed to a local JSONL so the
  common failure modes on this deployment are visible over time.
