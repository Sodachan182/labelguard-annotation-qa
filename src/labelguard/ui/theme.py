"""Design tokens (see .claude/skills/labelguard-design-system) and theme helpers."""

from __future__ import annotations

import streamlit as st

TOKENS: dict[str, dict[str, str]] = {
    "dark": {
        "bg-app": "#0D0F12",
        "bg-sidebar": "#121519",
        "bg-panel": "#171A20",
        "bg-hover": "#20242B",
        "border": "#272C34",
        "text-primary": "#EDF0F4",
        "text-secondary": "#A1A8B3",
        "text-muted": "#7C8592",
        "accent": "#8B98F9",
        "accent-hover": "#A3AEFF",
        "accent-soft": "rgba(139,152,249,0.14)",
        "critical": "#E88080",
        "warning": "#E5B567",
        "info": "#7FACE3",
        "success": "#6CC3A9",
    },
    "light": {
        "bg-app": "#F6F5F2",
        "bg-sidebar": "#EFEDE8",
        "bg-panel": "#FFFFFF",
        "bg-hover": "#ECEAE5",
        "border": "#DEDAD2",
        "text-primary": "#1D2229",
        "text-secondary": "#4D5562",
        "text-muted": "#6B7280",
        "accent": "#4F5BD5",
        "accent-hover": "#3E49B8",
        "accent-soft": "rgba(79,91,213,0.10)",
        "critical": "#B93A3A",
        "warning": "#9A6A12",
        "info": "#2F6DB0",
        "success": "#23795F",
    },
}

SEVERITY_GLYPH = {"critical": "●", "warning": "▲", "info": "■"}


def theme_type() -> str:
    """Active Streamlit theme ('dark' default). May lag one rerun after a switch."""
    try:
        t = st.context.theme.type
    except Exception:
        t = None
    return t if t in TOKENS else "dark"


def tokens() -> dict[str, str]:
    return TOKENS[theme_type()]


def plotly_layout(height: int = 260) -> dict:
    t = tokens()
    return {
        "height": height,
        "margin": {"l": 8, "r": 16, "t": 8, "b": 8},
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "rgba(0,0,0,0)",
        "font": {"family": "Geist, Segoe UI, system-ui, sans-serif", "size": 12, "color": t["text-secondary"]},
        "xaxis": {
            "gridcolor": t["border"],
            "zeroline": False,
            "linecolor": t["border"],
            "tickfont": {"color": t["text-muted"]},
            "title": {"font": {"size": 12, "color": t["text-muted"]}},
        },
        "yaxis": {
            "gridcolor": "rgba(0,0,0,0)",
            "zeroline": False,
            "linecolor": t["border"],
            "tickfont": {"color": t["text-secondary"]},
            "automargin": True,
            "title": {"font": {"size": 12, "color": t["text-muted"]}},
        },
        "showlegend": False,
        "hoverlabel": {
            "bgcolor": t["bg-panel"],
            "bordercolor": t["border"],
            "font": {"color": t["text-primary"], "family": "Geist, Segoe UI, sans-serif"},
        },
        "bargap": 0.35,
    }


PLOTLY_CONFIG = {"displayModeBar": False, "responsive": True}
