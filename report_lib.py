"""Builds a self-contained HTML export of the Results page (used by pages/3_Results.py)."""
from datetime import datetime
from html import escape

import plotly.graph_objects as go
import plotly.io as pio

_PAGE_CSS = """
body { font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 2rem; color: #1a1a1a; }
h1 { margin-bottom: 0; }
.subtitle { color: #666; margin-top: 0.25rem; }
h2 { margin-top: 2.5rem; border-bottom: 1px solid #ddd; padding-bottom: 0.3rem; }
table { border-collapse: collapse; margin-top: 0.5rem; }
th, td { padding: 4px 10px; text-align: right; }
th:first-child, td:first-child { text-align: left; }
.placeholder { color: #888; font-style: italic; }
"""


def _figure_html(fig: go.Figure | None, *, include_js: bool, placeholder: str) -> str:
    if fig is None:
        return f'<p class="placeholder">{escape(placeholder)}</p>'
    return pio.to_html(fig, full_html=False, include_plotlyjs=include_js)


def build_results_html(
    *,
    case_label: str,
    generated_at: datetime,
    lcoe_styler=None,
    cap_fig: go.Figure | None = None,
    pie_fig: go.Figure | None = None,
    nse_fig: go.Figure | None = None,
    cost_fig: go.Figure | None = None,
) -> str:
    figs = [
        ("Capacity Built", cap_fig, "No capacity data available."),
        ("Supply to Load Mix", pie_fig, "No generation-mix data available."),
        ("Unserved Energy by Time of Year", nse_fig, "No unserved energy in this run."),
        ("Cost Breakdown by Resource", cost_fig, "No cost breakdown data available."),
    ]

    body_parts = [
        f"<h1>GenX Results — {escape(case_label)}</h1>",
        f'<p class="subtitle">Generated {escape(generated_at.strftime("%Y-%m-%d %H:%M:%S"))}</p>',
        "<h2>Key Metrics</h2>",
        lcoe_styler.to_html() if lcoe_styler is not None else '<p class="placeholder">No LCOE data available.</p>',
    ]

    include_js_used = False
    for title, fig, placeholder in figs:
        body_parts.append(f"<h2>{escape(title)}</h2>")
        include_js = fig is not None and not include_js_used
        body_parts.append(_figure_html(fig, include_js=include_js, placeholder=placeholder))
        if include_js:
            include_js_used = True

    body = "\n".join(body_parts)
    return f"<!doctype html>\n<html>\n<head>\n<meta charset='utf-8'>\n<title>GenX Results — {escape(case_label)}</title>\n<style>{_PAGE_CSS}</style>\n</head>\n<body>\n{body}\n</body>\n</html>\n"
