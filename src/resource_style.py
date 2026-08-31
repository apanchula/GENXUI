"""Shared resource colour scheme.

Single source of truth for the type colours used by both the Results page
(pages/3_Results.py) and the Inputs fleet view (src/fleet_view.py), so the two
stay visually consistent.
"""
from __future__ import annotations

COLORS: dict[str, str] = {
    "thermal": "#4682b4",
    "solar":   "#ff8c00",
    "wind":    "#27ae60",
    "storage": "#2ecc71",
    "lds":     "#9b59b6",
    "grid":    "#f1c40f",
    "other":   "#888888",
}


def resource_type(name: str) -> str:
    """Stable type label for a resource, inferred from keywords in its name.
    One of: Thermal, Solar, Wind, Storage, LDS, Grid, Other."""
    n = str(name).lower()
    if any(k in n for k in ("gas", "ngcc", "natural_gas", "coal", "nuclear", "thermal",
                            "biomass", "allam")):
        return "Thermal"
    if any(k in n for k in ("pv", "solar")):
        return "Solar"
    if "wind" in n:
        return "Wind"
    if "lds" in n:
        return "LDS"
    if any(k in n for k in ("battery", "stor", "storage")):
        return "Storage"
    if "grid" in n:
        return "Grid"
    return "Other"


_TYPE_COLOR = {
    "Thermal": COLORS["thermal"], "Solar": COLORS["solar"], "Wind": COLORS["wind"],
    "Storage": COLORS["storage"], "LDS": COLORS["lds"], "Grid": COLORS["grid"],
    "Imports": "#5dade2", "Unserved": "#c0392b", "Other": COLORS["other"],
}


def resource_color(name: str) -> str:
    """Colour for a resource, inferred from keywords in its name."""
    return _TYPE_COLOR[resource_type(name)]


def type_color(type_label: str) -> str:
    return _TYPE_COLOR.get(type_label, COLORS["other"])
