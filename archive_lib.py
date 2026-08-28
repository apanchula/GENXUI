"""Shared archive/restore logic for GenXUI (used by pages/3_Results.py and pages/4_Archives.py).

An "archive" is a self-contained snapshot of one case's results/ output plus the
inputs (Run.jl, resources/, system/, policies/, settings/) that produced it, stored
under the user-configured workspace's archive directory (see `src/workspace.py`,
`workspace.archive_dir()`) so it survives the case folder being edited, re-run,
or deleted.
"""
import io
import json
import os
import re
import shutil
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src import workspace

INPUT_DIRS = ["resources", "system", "policies", "settings"]

_ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


class ArchiveError(Exception):
    """Raised for any user-facing archive/restore failure."""


def short_path(path: Path, root: Path) -> str:
    """Render `path` relative to `root` with a leading backslash, for display."""
    try:
        rel = path.relative_to(root)
    except ValueError:
        return str(path)
    return f"\\{rel.as_posix().replace('/', chr(92))}"


def sanitize_label(label: str | None) -> str | None:
    if not label:
        return None
    cleaned = _ILLEGAL_CHARS.sub("", label)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = cleaned.rstrip(". ")
    cleaned = cleaned[:60]
    if not cleaned or cleaned in (".", ".."):
        return None
    if cleaned.upper() in _RESERVED_NAMES:
        cleaned = f"_{cleaned}"
    return cleaned


def _unique_dir(parent: Path, name: str) -> Path:
    parent.mkdir(parents=True, exist_ok=True)
    candidate = parent / name
    suffix = 2
    while True:
        try:
            candidate.mkdir(parents=False, exist_ok=False)
            return candidate
        except FileExistsError:
            candidate = parent / f"{name}-{suffix}"
            suffix += 1


def get_genx_git_info(genx_root: Path) -> tuple[str | None, bool | None]:
    """Returns (short commit hash, dirty flag for TRACKED files only) or (None, None)."""
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(genx_root), capture_output=True, text=True, timeout=10,
        )
        if commit.returncode != 0:
            return None, None
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=str(genx_root), capture_output=True, text=True, timeout=10,
        )
        if dirty.returncode != 0:
            return commit.stdout.strip(), None
        return commit.stdout.strip(), bool(dirty.stdout.strip())
    except (FileNotFoundError, subprocess.SubprocessError):
        return None, None


def _read_csv(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    try:
        return pd.read_csv(path)
    except (pd.errors.ParserError, OSError):
        return None


def compute_headline_metrics(results_dir: Path) -> dict:
    """Cheap headline numbers for browsing an archive list. Not the full LCOE derivation."""
    metrics: dict = {
        "total_system_cost_musd_per_yr": None,
        "nse_pct_of_demand": None,
        "total_capacity_mw": None,
        "total_energy_capacity_mwh": None,
    }

    costs_df = _read_csv(results_dir / "costs.csv")
    if costs_df is not None and "Costs" in costs_df.columns and "Total" in costs_df.columns:
        costs = costs_df.set_index("Costs")["Total"]
        c_total = pd.to_numeric(costs.get("cTotal"), errors="coerce")
        if pd.notna(c_total):
            metrics["total_system_cost_musd_per_yr"] = float(c_total) / 1e6

    cap_df = _read_csv(results_dir / "capacity.csv")
    if cap_df is not None and "Resource" in cap_df.columns:
        total_row = cap_df[cap_df["Resource"].astype(str) == "Total"]
        if not total_row.empty:
            if "EndCap" in total_row.columns:
                v = pd.to_numeric(total_row["EndCap"].iloc[0], errors="coerce")
                if pd.notna(v):
                    metrics["total_capacity_mw"] = float(v)
            if "EndEnergyCap" in total_row.columns:
                v = pd.to_numeric(total_row["EndEnergyCap"].iloc[0], errors="coerce")
                if pd.notna(v):
                    metrics["total_energy_capacity_mwh"] = float(v)

    nse_mwh = None
    nse_df = _read_csv(results_dir / "nse.csv")
    if nse_df is not None and len(nse_df.columns) > 0:
        fc = nse_df.columns[0]
        row = nse_df[nse_df[fc].astype(str) == "AnnualSum"]
        if not row.empty and "Total" in nse_df.columns:
            v = pd.to_numeric(row["Total"].iloc[0], errors="coerce")
            if pd.notna(v):
                nse_mwh = float(v)

    demand_mwh = None
    pb_df = _read_csv(results_dir / "power_balance.csv")
    if pb_df is not None and len(pb_df.columns) > 0:
        fc = pb_df.columns[0]
        demand_cols = [c for c in pb_df.columns if c.split(".")[0] == "Demand"]
        if demand_cols:
            row = pb_df[pb_df[fc].astype(str) == "AnnualSum"]
            if not row.empty:
                v = pd.to_numeric(row[demand_cols].iloc[0], errors="coerce").fillna(0)
                demand_mwh = abs(float(v.sum()))

    if nse_mwh is not None and demand_mwh:
        metrics["nse_pct_of_demand"] = 100.0 * nse_mwh / demand_mwh

    return metrics


def create_archive(case_path: Path, genx_root: Path, *, label: str | None = None) -> Path:
    archive_root = workspace.archive_dir()
    # GenX may have written results/, or results_1/, results_2/… — archive the latest.
    results_src = workspace.resolve_results_dir(case_path)
    if results_src is None:
        raise ArchiveError(f"No results found for `{case_path.name}` — run the model first.")

    clean_label = sanitize_label(label)
    local_ts = datetime.now()
    stem = f"{case_path.name}__{local_ts:%Y%m%d-%H%M%S}"
    if clean_label:
        stem = f"{stem}__{clean_label}"

    tmp_dir = archive_root / f".tmp_{stem}"
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)

    try:
        tmp_dir.mkdir(parents=True)

        shutil.copytree(results_src, tmp_dir / "results")

        inputs_dir = tmp_dir / "inputs"
        inputs_dir.mkdir()
        for dir_name in INPUT_DIRS:
            src = case_path / dir_name
            if src.exists():
                shutil.copytree(src, inputs_dir / dir_name)
        run_jl = case_path / "Run.jl"
        if run_jl.exists():
            shutil.copy2(run_jl, inputs_dir / "Run.jl")

        metrics = compute_headline_metrics(tmp_dir / "results")
        commit, dirty = get_genx_git_info(genx_root)

        manifest = {
            "schema_version": 1,
            "case_name": case_path.name,
            "archived_at": datetime.now(timezone.utc).isoformat(),
            "label": clean_label,
            "genx_commit": commit,
            "genx_commit_dirty": dirty,
            "metrics": metrics,
            "archive_dir_name": stem,
        }
        (tmp_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

        final_dir = archive_root / stem
        suffix = 2
        while True:
            try:
                os.rename(tmp_dir, final_dir)
                return final_dir
            except (FileExistsError, OSError):
                if final_dir.exists():
                    final_dir = archive_root / f"{stem}-{suffix}"
                    suffix += 1
                    continue
                raise
    except Exception:
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)
        raise


def read_manifest(archive_dir: Path) -> dict:
    manifest_path = archive_dir / "manifest.json"
    if not manifest_path.exists():
        raise ArchiveError(f"`{archive_dir.name}` has no manifest.json — not a valid archive.")
    return json.loads(manifest_path.read_text())


def list_archives() -> list[dict]:
    archive_root = workspace.archive_dir()
    if not archive_root.exists():
        return []
    archives = []
    for d in archive_root.iterdir():
        if not d.is_dir() or d.name.startswith(".tmp_"):
            continue
        try:
            manifest = read_manifest(d)
        except ArchiveError:
            continue
        manifest["path"] = str(d)
        archives.append(manifest)
    archives.sort(key=lambda m: m.get("archived_at", ""), reverse=True)
    return archives


def build_zip_bytes(archive_dir: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in archive_dir.rglob("*"):
            if f.is_file():
                zf.write(f, arcname=str(f.relative_to(archive_dir.parent)))
    return buf.getvalue()


def check_commit_mismatch(manifest: dict, genx_root: Path) -> str | None:
    archived_commit = manifest.get("genx_commit")
    if not archived_commit:
        return "This archive was created without a recorded GenX.jl commit — cannot verify reproducibility."
    current_commit, _ = get_genx_git_info(genx_root)
    if not current_commit:
        return "Could not read the current GenX.jl commit — cannot verify reproducibility."
    if current_commit != archived_commit:
        return (
            f"GenX.jl has moved since this archive was made (archived at `{archived_commit}`, "
            f"now at `{current_commit}`) — re-running may not reproduce these results exactly."
        )
    if manifest.get("genx_commit_dirty"):
        return "GenX.jl had uncommitted changes to tracked files when this archive was made."
    return None


def restore_archive_to_new_case(archive_dir: Path) -> Path:
    """Restore a saved archive's inputs as a new case in the active workspace's
    data_dir() (not the legacy GenX.jl tree — see GENXUI-1)."""
    manifest = read_manifest(archive_dir)
    inputs_dir = archive_dir / "inputs"
    if not inputs_dir.exists():
        raise ArchiveError(f"`{archive_dir.name}` has no saved inputs to restore.")

    case_name = manifest.get("case_name", "case")
    local_ts = datetime.now()
    new_name = f"{case_name}_replay_{local_ts:%Y%m%d-%H%M%S}"
    new_case_dir = _unique_dir(workspace.data_dir(), new_name)

    try:
        for dir_name in INPUT_DIRS:
            src = inputs_dir / dir_name
            if src.exists():
                shutil.copytree(src, new_case_dir / dir_name)
        run_jl = inputs_dir / "Run.jl"
        if run_jl.exists():
            shutil.copy2(run_jl, new_case_dir / "Run.jl")
        return new_case_dir
    except Exception:
        shutil.rmtree(new_case_dir, ignore_errors=True)
        raise
