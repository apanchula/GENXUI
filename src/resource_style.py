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


def resource_color(name: str) -> str:
    """Colour for a resource, inferred from keywords in its name."""
    n = str(name).lower()
    if any(k in n for k in ("gas", "ngcc", "natural_gas", "coal", "nuclear", "thermal")):
        return COLORS["thermal"]
    if any(k in n for k in ("pv", "solar")):
        return COLORS["solar"]
    if "wind" in n:
        return COLORS["wind"]
    if "lds" in n:
        return COLORS["lds"]
    if any(k in n for k in ("battery", "stor", "storage")):
        return COLORS["storage"]
    if "grid" in n:
        return COLORS["grid"]
    return COLORS["other"]
