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
from pathlib import Path

CONFIG_DIR = Path.home() / ".genxui"
CONFIG_PATH = CONFIG_DIR / "config.json"

# Repo root (parent of this src/ directory) — used only to locate legacy,
# pre-workspace locations for the import/migration-notice helpers below.
_REPO_ROOT = Path(__file__).resolve().parent.parent

DATA_DIRNAME = "data"
ARCHIVE_DIRNAME = "archive"


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


# ── Legacy-location helpers (import + migration notice only) ──────────────────
# These point at the pre-GENXUI-1 locations so users aren't stranded by the
# directory-model change: cases used to live inside `../GenX.jl/`, and
# archives used to live in a fixed sibling `../archives/` directory.

def legacy_genx_root() -> Path:
    return _REPO_ROOT.parent / "GenX.jl"


def legacy_archive_root() -> Path:
    return _REPO_ROOT.parent / "archives"


def list_legacy_cases() -> list[str]:
    """Cases discoverable the old way, inside `../GenX.jl/` — used by the
    'Import case from GenX.jl' action so pre-existing cases aren't stranded."""
    root = legacy_genx_root()
    if not root.exists():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir() and (p / "Run.jl").exists())


def import_case_from_legacy(case_name: str) -> Path:
    """Copy a case folder from the legacy `../GenX.jl/<case_name>` location into
    the configured workspace's data_dir(). Raises FileNotFoundError / FileExistsError
    on bad input rather than silently overwriting an existing imported case."""
    import shutil

    src = legacy_genx_root() / case_name
    if not src.exists() or not (src / "Run.jl").exists():
        raise FileNotFoundError(f"No case named '{case_name}' found under {legacy_genx_root()}")

    dest = data_dir() / case_name
    if dest.exists():
        raise FileExistsError(f"'{case_name}' already exists in the active workspace data directory.")

    shutil.copytree(src, dest)
    return dest


def has_unmigrated_legacy_archives() -> bool:
    """True if archives exist at the old fixed sibling location and that
    location differs from the currently configured archive_dir() — signal for
    a one-time informational notice, never a silent auto-migration."""
    legacy = legacy_archive_root()
    if not legacy.exists() or not any(legacy.iterdir()):
        return False
    root = get_workspace_root()
    if root is None:
        return True
    return legacy.resolve() != archive_dir().resolve()
