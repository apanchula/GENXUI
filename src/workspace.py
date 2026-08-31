"""User-configurable workspace root for GenXUI (GENXUI-1).

Replaces the old model of scanning `../GenX.jl` for cases and archiving to a
fixed sibling `archives/` directory. Instead the user chooses one workspace
root that contains:

    <root>/data/      active/current GenX runs and case inputs
    <root>/archive/   historical/saved case runs and output snapshots

The chosen root is persisted to `~/.genxui/config.json` so it survives a full
server restart, not just a Streamlit page rerun.
"""
import json
import re
import shutil
from pathlib import Path

CONFIG_DIR = Path.home() / ".genxui"
CONFIG_PATH = CONFIG_DIR / "config.json"

# Repo root (parent of this src/ directory) — used only to locate legacy,
# pre-workspace locations for the import/migration-notice helpers below.
_REPO_ROOT = Path(__file__).resolve().parent.parent

DATA_DIRNAME = "data"
ARCHIVE_DIRNAME = "archive"

# Filesystem-name rules shared with archive_lib (single source of truth).
ILLEGAL_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

# Generated sub-directories that a "clean" case copy should drop.
_GENERATED_DIRS = ("TDR_results", "Full_TimeSeries")


class WorkspaceNotConfiguredError(Exception):
    """Raised when data_dir()/archive_dir() are used before a root is set."""


def _read_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _write_config(cfg: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


def get_workspace_root() -> Path | None:
    """Return the configured workspace root, or None if unset."""
    root = _read_config().get("workspace_root")
    return Path(root) if root else None


def set_workspace_root(path: Path) -> None:
    """Persist `path` as the workspace root and ensure data/ and archive/ exist.

    Idempotent — safe to call again against the same root (e.g. a prior
    partial run, or the user reopening the app with a root already set).
    """
    path = Path(path).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    (path / DATA_DIRNAME).mkdir(parents=True, exist_ok=True)
    (path / ARCHIVE_DIRNAME).mkdir(parents=True, exist_ok=True)

    cfg = _read_config()
    cfg["workspace_root"] = str(path)
    _write_config(cfg)


def data_dir() -> Path:
    root = get_workspace_root()
    if root is None:
        raise WorkspaceNotConfiguredError("No workspace root configured — call set_workspace_root() first.")
    d = root / DATA_DIRNAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def archive_dir() -> Path:
    root = get_workspace_root()
    if root is None:
        raise WorkspaceNotConfiguredError("No workspace root configured — call set_workspace_root() first.")
    d = root / ARCHIVE_DIRNAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def discover_cases() -> list[str]:
    """List subdirectories of data_dir() that look like a GenX case (contain Run.jl)."""
    d = data_dir()
    return sorted(p.name for p in d.iterdir() if p.is_dir() and (p / "Run.jl").exists())


# ── Case management (GENXUI-6) ──────────────────────────────────────────────

def case_dir(name: str) -> Path:
    """`data_dir() / name` — a plain join, no validation."""
    return data_dir() / name


def valid_case_name(name: str) -> str | None:
    """Return a cleaned single-segment directory name, or None if `name` isn't
    usable as one. Whitespace is collapsed and outer dots/spaces trimmed;
    anything containing `<>:"/\\|?*` or a control char, `.`/`..`, or a
    Windows-reserved stem is rejected outright. Collisions are the caller's job.
    """
    if not name or ILLEGAL_NAME_CHARS.search(name):
        return None
    cleaned = re.sub(r"\s+", " ", name).strip().strip(". ")
    if not cleaned or cleaned in (".", "..") or cleaned.upper() in RESERVED_NAMES:
        return None
    return cleaned


def _require_case(name: str) -> Path:
    src = case_dir(name)
    if not src.is_dir() or not (src / "Run.jl").exists():
        raise FileNotFoundError(f"No case named '{name}' in the workspace data directory.")
    return src


def _require_free_name(new: str) -> Path:
    clean = valid_case_name(new)
    if clean is None:
        raise ValueError(f"'{new}' is not a usable case name.")
    dest = case_dir(clean)
    if dest.exists():
        raise FileExistsError(f"A case named '{clean}' already exists.")
    return dest


def rename_case(old: str, new: str) -> Path:
    """Move `data/old` -> `data/<clean new>`. The whole folder moves; Run.jl is
    location-independent so results/ etc. ride along."""
    src = _require_case(old)
    dest = _require_free_name(new)
    shutil.move(str(src), str(dest))
    return dest


def duplicate_case(src_name: str, new: str, *, inputs_only: bool = False) -> Path:
    """Copy `data/src_name` -> `data/<clean new>`. With inputs_only, only Run.jl
    plus resources/ system/ policies/ settings/ are copied (a clean re-run
    starting point)."""
    src = _require_case(src_name)
    dest = _require_free_name(new)
    if not inputs_only:
        shutil.copytree(src, dest)
        return dest

    dest.mkdir(parents=True)
    for name in ("resources", "system", "policies", "settings"):
        sub = src / name
        if sub.is_dir():
            shutil.copytree(sub, dest / name)
    for f in src.glob("*.jl"):
        shutil.copy2(f, dest / f.name)
    return dest


def delete_case(name: str) -> None:
    """Permanently remove `data/name`. Archived runs under archive/ are untouched."""
    src = case_dir(name)
    if not src.is_dir():
        raise FileNotFoundError(f"No case named '{name}' in the workspace data directory.")
    shutil.rmtree(src)


def resolve_results_dir(case_path: Path) -> Path | None:
    """The results folder GenXUI should display / archive for a case.

    GenX writes to `results/` on the first run, then `results_1/`, `results_2/`,
    … on subsequent runs unless `OverwriteResults: 1` is set (see
    `src/run_settings.py`). This picks the run the user actually means:

      - the most recently modified of `results/` and any `results_N/`
        (ignoring empty ones), suffix number as the tie-breaker;
      - `None` when the case has no results at all.

    Most-recent-mtime (not highest suffix) is deliberate: once GenXUI runs
    overwrite `results/` in place, a fresh `results/` must win over a stale
    `results_1/` left over from the old fan-out behaviour.

    Does NOT descend into the multi-stage `results/results_p*/` layout.
    """
    candidates: list[tuple[float, int, Path]] = []

    plain = case_path / "results"
    if plain.is_dir() and any(plain.iterdir()):
        candidates.append((plain.stat().st_mtime, 0, plain))

    for p in case_path.glob("results_*"):
        m = re.fullmatch(r"results_(\d+)", p.name)
        if m and p.is_dir() and any(p.iterdir()):
            candidates.append((p.stat().st_mtime, int(m.group(1)), p))

    if not candidates:
        return None
    return max(candidates)[2]


# ── GenX.jl checkout / legacy-location helpers ───────────────────────────────
# legacy_genx_root() is the sibling GenX.jl clone — still used for the bundled
# example_systems, the docs snapshot fallback, and archive git-commit tracking.

def legacy_genx_root() -> Path:
    return _REPO_ROOT.parent / "GenX.jl"
