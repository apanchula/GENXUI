"""GenX.jl reference content for GenXUI's inline help and Help page (GENXUI-3).

Content is read from a bundled snapshot of the GenX docs under `reference/genx/`,
or — when a GenX.jl checkout is present at `workspace.legacy_genx_root()` — from
its live `docs/src/` (fresher). No network access; everything is local files.

Public API
----------
- settings_help(key)            -> ParamHelp | None   # a genx_settings.yml key
- column_help(file_stem, column) -> str | None        # an input CSV column
- topics()                      -> list[Topic]        # for the Help page
- topic_body(slug)              -> str                # cleaned markdown
- search(query)                 -> list[DocHit]       # across all reference docs
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from src import workspace

_BUNDLED_DIR = Path(__file__).resolve().parent.parent / "reference" / "genx"

# slug -> (bundled filename, path under GenX.jl/docs/src/)
_DOCS: dict[str, tuple[str, str]] = {
    "settings": ("model_configuration.md", "User_Guide/model_configuration.md"),
    "inputs":   ("model_input.md",         "User_Guide/model_input.md"),
    "outputs":  ("model_output.md",        "User_Guide/model_output.md"),
    "tdr":      ("TDR_input.md",           "User_Guide/TDR_input.md"),
    "intro":    ("model_introduction.md",  "Model_Concept_Overview/model_introduction.md"),
}

_TOPIC_TITLES: dict[str, str] = {
    "intro":    "GenX model overview",
    "settings": "Model settings (genx_settings.yml)",
    "tdr":      "Time domain reduction",
    "inputs":   "Input files & columns",
    "outputs":  "Output files & columns",
}

# Resource .csv files that inherit the "common to all resources" column table.
_RESOURCE_STEMS = {
    "thermal", "vre", "storage", "hydro", "must_run", "flex_demand",
    "electrolyzer", "vre_stor", "allam_cycle_lox",
}
_RESOURCE_COMMON = "__resource_common__"

_HOSTED_DOCS_URL = "https://genxproject.github.io/GenX.jl/stable/"


# ── data types ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ParamHelp:
    key: str
    summary: str
    values: tuple[str, ...] = ()

    def as_markdown(self) -> str:
        md = self.summary or ""
        if self.values:
            md += ("\n\n" if md else "") + "\n".join(f"- {v}" for v in self.values)
        return md.strip()


@dataclass(frozen=True)
class Topic:
    slug: str
    title: str
    available: bool


@dataclass(frozen=True)
class DocHit:
    topic_slug: str
    topic_title: str
    section: str
    snippet: str


# ── doc loading ──────────────────────────────────────────────────────────────

def _doc_text(slug: str) -> str | None:
    entry = _DOCS.get(slug)
    if entry is None:
        return None
    bundled_name, live_rel = entry
    live = workspace.legacy_genx_root() / "docs" / "src" / live_rel
    for candidate in (live, _BUNDLED_DIR / bundled_name):
        try:
            if candidate.is_file():
                return candidate.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    return None


def _unescape(s: str) -> str:
    return s.replace("\\_", "_").replace("\\|", "|").replace("\\-", "-")


def _split_row(line: str) -> list[str] | None:
    """A markdown table row -> list of trimmed cells, or None if not a row."""
    s = line.strip()
    if not s.startswith("|"):
        return None
    s = s[1:-1] if s.endswith("|") else s[1:]
    return [c.strip() for c in s.split("|")]


def _is_separator(cells: list[str]) -> bool:
    return all(set(c) <= set(":- ") and "-" in c for c in cells if c)


# ── settings / TDR key tables ────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _kv_index() -> dict[str, ParamHelp]:
    """{param key -> ParamHelp} merged from the settings and TDR references.

    Both docs are flat 2-column tables (`|Name | Description|`) with optional
    continuation rows (`|| more text|`) that carry the enumerated values.
    """
    out: dict[str, ParamHelp] = {}
    for slug in ("settings", "tdr"):
        md = _doc_text(slug)
        if not md:
            continue
        cur_key: str | None = None
        cur_summary = ""
        cur_values: list[str] = []

        def flush():
            nonlocal cur_key
            if cur_key:
                out[cur_key] = ParamHelp(cur_key, cur_summary.strip(),
                                         tuple(cur_values))
            cur_key = None

        for line in md.splitlines():
            cells = _split_row(line)
            if cells is None or _is_separator(cells):
                continue
            if len(cells) < 2:
                continue
            name, desc = cells[0], _strip_inline(_unescape(" | ".join(cells[1:]).strip()))
            name_clean = _unescape(name).strip().strip("`").strip()
            # Header row or bold-only group label -> not a parameter, not a
            # continuation. (A real continuation row has an empty name cell that
            # does NOT start with '**'.)
            if name.startswith("**") or name_clean.lower() in (
                "parameter", "key", "column name", "output"
            ):
                continue
            if name_clean:                       # new parameter row
                flush()
                cur_key = name_clean
                cur_summary = desc
                cur_values = []
                # Some rows pack the first enumerated value into the desc cell.
                if re.match(r"^-?\d+\s*=\s*.+", cur_summary):
                    cur_values.append(cur_summary)
                    cur_summary = ""
            elif desc:                           # continuation row
                cur_values.append(desc)
        flush()
    return out


def _strip_inline(s: str) -> str:
    s = re.sub(r"\[([^\]]+)\]\(@ref[^)]*\)", r"\1", s)
    s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)
    return s.strip()


def settings_help(key: str) -> ParamHelp | None:
    """Help for a `genx_settings.yml` (or `time_domain_reduction_settings.yml`)
    key. GenX setting names are case-sensitive; we try exact first, then a
    case-insensitive match as a convenience."""
    idx = _kv_index()
    if key in idx:
        return idx[key]
    low = key.lower()
    for k, v in idx.items():
        if k.lower() == low:
            return v
    return None


# ── input / output column tables ─────────────────────────────────────────────

@lru_cache(maxsize=2)
def _column_index(slug: str) -> dict[str, dict[str, str]]:
    """{file stem -> {column -> description}} for an input/output reference doc.

    Scope is tracked from the nearest heading: a heading naming `<X>.csv` sets
    the scope to `x`; a heading about columns "common to all resources" sets it
    to the shared bucket every resource file falls back to.
    """
    md = _doc_text(slug)
    out: dict[str, dict[str, str]] = {}
    if not md:
        return out

    scope: str | None = None
    last_col: str | None = None

    for line in md.splitlines():
        h = re.match(r"^#{1,6}\s+(.*)$", line)
        if h:
            title = h.group(1)
            if re.search(r"common to all resources", title, re.I):
                scope = _RESOURCE_COMMON
            else:
                m = re.search(r"([A-Za-z][\w\\]*)\.csv", title)
                scope = _unescape(m.group(1)).lower() if m else scope
            last_col = None
            continue

        cells = _split_row(line)
        if cells is None or _is_separator(cells) or scope is None:
            continue
        if len(cells) < 2:
            continue
        name = _unescape(cells[0]).strip().strip("`").strip()
        desc = _strip_inline(_unescape(cells[1].strip()))
        units = cells[2].strip() if len(cells) > 2 else ""
        if units and units.lower() != "units":
            desc = f"{desc} ({units})" if desc else f"({units})"
        if name.lower() in ("column name", "output", "key", "parameter"):
            continue
        if cells[0].startswith("**") or (name and not desc):
            continue  # bold-only group label
        bucket = out.setdefault(scope, {})
        if name:
            bucket[name.lower()] = desc
            last_col = name.lower()
        elif desc and last_col:                  # continuation row
            bucket[last_col] = f"{bucket[last_col]} {desc}".strip()

    return out


_STEM_ALIASES = {
    "load_data": "demand_data",
    "generators_variability": "generator_variability",
}


def column_help(file_stem: str, column: str) -> str | None:
    """One-line description for an input/output CSV column, or None.

    `file_stem` may be a filename or a stem ("Thermal", "Thermal.csv",
    "CO2_cap"). Resource files fall back to the columns common to all resources.
    """
    stem = file_stem.lower()
    if stem.endswith(".csv"):
        stem = stem[:-4]
    stem = _STEM_ALIASES.get(stem, stem)
    col = column.lower()
    # Doc tables use a `*` wildcard for indexed columns (CO_2_Max_Mtons_*,
    # ESR_1, DerateCapRes_1, …); try the wildcard forms too.
    variants = [col]
    m = re.match(r"^(.*?)_?(\d+)$", col)
    if m:
        variants += [f"{m.group(1)}_*", f"{m.group(1)}*", f"{m.group(1)}_z*"]

    for slug in ("inputs", "outputs"):
        idx = _column_index(slug)
        scopes = [stem]
        if stem in _RESOURCE_STEMS:
            scopes.append(_RESOURCE_COMMON)
        for sc in scopes:
            table = idx.get(sc, {})
            for v in variants:
                if table.get(v):
                    return table[v]
            # last resort: underscore-insensitive match
            squashed = col.replace("_", "")
            for k, v in table.items():
                if v and k.replace("_", "").rstrip("*") == squashed:
                    return v
    return None


def documented_columns(file_stem: str, columns: list[str]) -> list[tuple[str, str]]:
    """(column, description) for those `columns` that have help, in input order."""
    out = []
    for c in columns:
        h = column_help(file_stem, c)
        if h:
            out.append((c, h))
    return out


# ── Help page: topics & search ───────────────────────────────────────────────

def topics() -> list[Topic]:
    return [
        Topic(slug, _TOPIC_TITLES[slug], _doc_text(slug) is not None)
        for slug in _TOPIC_TITLES
    ]


_RAW_HTML_BLOCK = re.compile(r"```@raw html\n(.*?)\n```", re.S)
_DOCS_BLOCK = re.compile(r"```@(?:docs|autodocs)\n.*?\n```", re.S)


def _clean(md: str) -> str:
    def _html_to_md(m: re.Match) -> str:
        body = m.group(1)
        body = re.sub(r"<li[^>]*>(.*?)</li>", r"- \1", body, flags=re.S)
        body = re.sub(r"</?[a-zA-Z][^>]*>", "", body)
        return body.strip()

    md = _RAW_HTML_BLOCK.sub(_html_to_md, md)
    md = _DOCS_BLOCK.sub("", md)
    md = re.sub(r"^!!!\s+\w+(?:\s+\"([^\"]*)\")?\s*$",
                lambda m: f"**{m.group(1) or 'Note'}**", md, flags=re.M)
    md = re.sub(r"\[([^\]]+)\]\(@ref[^)]*\)", r"\1", md)
    md = md.replace("\\_", "_").replace("\\-", "-")   # Documenter escapes
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip()


def topic_body(slug: str) -> str:
    md = _doc_text(slug)
    if md is None:
        return "_Reference content not available._"
    return _clean(md)


@dataclass(frozen=True)
class _Section:
    topic_slug: str
    topic_title: str
    heading: str
    text: str


@lru_cache(maxsize=1)
def _all_sections() -> tuple[_Section, ...]:
    sections: list[_Section] = []
    for slug, title in _TOPIC_TITLES.items():
        md = _doc_text(slug)
        if not md:
            continue
        md = _clean(md)
        cur_head = title
        buf: list[str] = []

        def flush():
            if buf:
                sections.append(_Section(slug, title, cur_head,
                                         "\n".join(buf).strip()))

        for line in md.splitlines():
            h = re.match(r"^#{1,6}\s+(.*)$", line)
            if h:
                flush()
                buf = []
                cur_head = h.group(1).strip()
            else:
                buf.append(line)
        flush()
    return tuple(sections)


def search(query: str, limit: int = 20) -> list[DocHit]:
    tokens = [t for t in re.split(r"\s+", query.lower().strip()) if t]
    if not tokens:
        return []
    scored: list[tuple[int, DocHit]] = []
    for sec in _all_sections():
        head = sec.heading.lower()
        hay = f"{head}\n{sec.text}".lower()
        if not all(t in hay for t in tokens):
            continue
        # Heading matches dominate — a section titled after the query is what
        # the user wants, not one that merely mentions the words a lot.
        score = sum(hay.count(t) for t in tokens)
        score += 20 * sum(t in head for t in tokens)
        if all(t in head for t in tokens):
            score += 100
        scored.append((score, DocHit(sec.topic_slug, sec.topic_title,
                                     sec.heading, _snippet(sec.text, tokens[0]))))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [hit for _, hit in scored[:limit]]


def _snippet(text: str, token: str, width: int = 160) -> str:
    flat = re.sub(r"\s+", " ", text).strip()
    i = flat.lower().find(token)
    if i < 0:
        return flat[:width] + ("…" if len(flat) > width else "")
    start = max(0, i - width // 3)
    end = min(len(flat), start + width)
    return ("…" if start else "") + flat[start:end] + ("…" if end < len(flat) else "")


def hosted_docs_url() -> str:
    return _HOSTED_DOCS_URL
