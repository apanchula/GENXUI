"""Post-mortem diagnosis of a GenX run from its combined stdout+stderr.

`stream_process()` in app.py merges stderr into stdout, so the entire run
transcript is available as one string. After the Julia process exits we run
that transcript (plus the return code) through an ordered catalog of failure
signatures and surface the first match as a RunDiagnosis the UI can render as a
real status callout — the raw terminal output is never modified.

Pure functions, no Streamlit import — see tests/test_run_diagnosis.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

Severity = Literal["error", "warning"]

_DOCS_URL = "https://genxproject.github.io/GenX.jl/stable/"


@dataclass(frozen=True)
class RunDiagnosis:
    signature_id: str          # stable id, for telemetry / tests / bug reports
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
    match: Callable[[str, int], bool]   # (transcript_lower, returncode) -> bool
    docs_url: str | None = None


def _all(*needles: str) -> Callable[[str, int], bool]:
    lowered = tuple(n.lower() for n in needles)
    return lambda text, rc: all(n in text for n in lowered)


def _any(*needles: str) -> Callable[[str, int], bool]:
    lowered = tuple(n.lower() for n in needles)
    return lambda text, rc: any(n in text for n in lowered)


# Ordered most-specific first. diagnose() returns the first signature whose
# match() is true. Generic patterns (julia_load_error) stay last so a precise
# cause wins; warning-severity entries are the only ones allowed to fire on an
# otherwise-successful run (returncode 0).
_CATALOG: list[_Signature] = [

    _Signature(
        id="julia_not_found",
        severity="error",
        title="Julia isn't available",
        detail="The 'julia' command could not be found on this system's PATH.",
        remedy="Install Julia (https://julialang.org/downloads) and confirm "
               "`julia --version` works in a normal terminal, then retry.",
        match=_any("'julia' not found on path"),
    ),

    _Signature(
        id="out_of_memory",
        severity="error",
        title="Ran out of memory",
        detail="The solver could not allocate enough RAM to build or solve this "
               "case on this machine. Larger cases (full-year hourly, many "
               "resources, electrolyzers, multi-stage) need substantially more "
               "memory.",
        remedy="Close other applications to free up memory and run it again. If "
               "it still fails, try a smaller case, or set the solver Method to "
               "`simplex` in the case's settings/highs_settings.yml "
               "(interior-point uses far more memory).",
        match=_any(
            "std::bad_alloc",                   # HiGHS / C++ allocation failure
            "outofmemoryerror",                 # Julia
            "the paging file is too small",     # Windows, typically during precompile
            "error opening package file",       # Windows precompile OOM tell
            "cannot allocate memory",           # Linux
            "out of memory",
        ),
        docs_url=_DOCS_URL,
    ),

    _Signature(
        id="model_infeasible",
        severity="error",
        title="No feasible solution",
        detail="The optimization problem has no solution that satisfies every "
               "constraint — usually a policy constraint (CO2 cap, capacity "
               "reserve margin, min/max capacity requirement) that the available "
               "resources cannot meet.",
        remedy="Relax or disable the binding policy in settings/genx_settings.yml, "
               "add capacity headroom, or enable that policy's slack variables "
               "(see the 4_three_zones_w_policies_slack example).",
        # Deliberately not matching bare "infeasibilit*" — the HiGHS simplex
        # log prints an "Infeasibilities" column header on every solve.
        match=_any(": infeasible", "is infeasible", "primal infeasible",
                   "problem infeasible", "model is infeasible"),
    ),

    _Signature(
        id="model_unbounded",
        severity="error",
        title="Model is unbounded",
        detail="The objective can be improved without limit — typically a "
               "missing upper bound or a negative-cost resource with no cap.",
        remedy="Check for resources with zero or negative cost and no "
               "Max_Cap_MW, and confirm demand and policy inputs loaded "
               "correctly.",
        match=_any(": unbounded", "primal unbounded", "is unbounded"),
    ),

    _Signature(
        id="solver_time_limit",
        severity="error",
        title="Solver hit its time limit",
        detail="HiGHS stopped before converging because it reached the "
               "configured time limit.",
        remedy="Raise TimeLimit in settings/highs_settings.yml, reduce the model "
               "size (time-domain reduction, fewer resources), or switch the "
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
               "that the settings/ files and the resources/ and system/ CSVs "
               "exist and are named exactly as GenX expects.",
        match=_any("systemerror", "no such file or directory", "could not find",
                   "isadirectoryerror"),
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
        match=_all("argumenterror", "not found"),
    ),

    _Signature(
        id="objective_scaling",
        severity="warning",
        title="Large objective coefficients",
        detail="HiGHS flagged excessively large costs in the objective. The run "
               "still completed, but poor scaling can hurt solver accuracy and "
               "speed.",
        remedy="No action required. If results look off, review the largest "
               "cost inputs, or enable ParameterScale in settings/genx_settings.yml.",
        match=_any("excessively large costs"),
    ),

    _Signature(
        id="julia_load_error",
        severity="error",
        title="The run crashed with a Julia error",
        detail="Julia raised an unhandled error while running the case. The "
               "specific message is in the terminal output above.",
        remedy="Read the first `ERROR:` line in the terminal output — it names "
               "the actual problem. If it points at your inputs, fix those; "
               "otherwise capture the full output for a bug report.",
        match=_any("error: loaderror", "\nerror:", "unhandled exception"),
    ),
]


_GENERIC_FAIL = RunDiagnosis(
    signature_id="unknown_failure",
    severity="error",
    title="The run failed",
    detail="GenX exited with a non-zero status but no known failure pattern was "
           "recognised in its output.",
    remedy="Scan the terminal output for the first `ERROR:` or `WARNING:` line. "
           "If you can't tell what went wrong, capture the full output for a "
           "bug report.",
)


def diagnose(transcript: str, returncode: int) -> RunDiagnosis | None:
    """Diagnose a finished GenX run.

    - returncode 0, no warning signature  -> None (clean success)
    - returncode 0, warning signature     -> warning-severity RunDiagnosis
    - returncode != 0                     -> first matching signature, else
                                             _GENERIC_FAIL
    """
    text = transcript.lower()

    for sig in _CATALOG:
        # On a clean exit only warning signatures may fire; a stray "error:"
        # in otherwise-fine output shouldn't raise a false alarm.
        if returncode == 0 and sig.severity != "warning":
            continue
        if sig.match(text, returncode):
            return RunDiagnosis(
                signature_id=sig.id, severity=sig.severity, title=sig.title,
                detail=sig.detail, remedy=sig.remedy, docs_url=sig.docs_url,
            )

    if returncode != 0:
        return _GENERIC_FAIL
    return None
