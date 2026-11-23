"""Scoped CSS and small HTML building blocks.

Selectors use Streamlit's documented ``st-key-<key>`` container classes and
``data-testid`` attributes only — never generated class names. Every dynamic
string that reaches HTML passes through :func:`esc`, because dataset names,
labels and file names come from untrusted files.
"""

from __future__ import annotations

import html

import streamlit as st

from labelguard.ui.theme import SEVERITY_GLYPH, theme_type, tokens


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _css() -> str:
    t = tokens()
    v = "\n".join(f"  --lg-{k}: {val};" for k, val in t.items())
    return f"""
<style>
:root {{
{v}
  --lg-radius-sm: 6px;
  --lg-radius-md: 10px;
  --lg-radius-lg: 14px;
}}
[data-testid="stMainBlockContainer"] {{
  padding-top: 2.25rem; padding-bottom: 3rem;
  padding-left: 2rem; padding-right: 2rem; max-width: 1480px;
}}
header[data-testid="stHeader"] {{ background: transparent; }}
[data-testid="stAppDeployButton"], [data-testid="stDecoration"] {{ display: none; }}
body, [data-testid="stApp"] {{ font-feature-settings: "cv11", "ss01"; }}
[data-testid="stSidebarNav"] a span {{ font-size: 14px; }}
[data-testid="stSidebarNavLink"] {{ border-radius: var(--lg-radius-sm); }}
[data-testid="stSidebarNavLink"][aria-current="page"] {{ background: var(--lg-accent-soft); }}
[data-testid="stSidebarNavLink"][aria-current="page"] span {{ color: var(--lg-text-primary); font-weight: 560; }}

*:focus-visible {{ outline: 2px solid var(--lg-accent) !important; outline-offset: 2px; }}
@media (prefers-reduced-motion: reduce) {{
  *, *::before, *::after {{ transition: none !important; animation: none !important; }}
}}

/* page header */
.lg-head {{ display: flex; flex-direction: column; gap: 4px; margin-bottom: 2px; }}
.lg-head h1 {{ font-size: 26px; line-height: 1.25; font-weight: 600; margin: 0; padding: 0;
  letter-spacing: -0.01em; color: var(--lg-text-primary); }}
.lg-head p {{ margin: 0; color: var(--lg-text-secondary); font-size: 14px; }}
.lg-context {{ font-size: 13px; color: var(--lg-text-muted); margin-top: 6px; }}
.lg-context b {{ color: var(--lg-text-secondary); font-weight: 560; }}
.lg-rule {{ height: 1px; background: var(--lg-border); margin: 14px 0 22px 0; border: 0; }}
.lg-section {{ font-size: 16px; font-weight: 600; color: var(--lg-text-primary); margin: 8px 0 2px 0; }}
.lg-sub {{ font-size: 13px; color: var(--lg-text-muted); margin: 0 0 10px 0; }}

/* metric strip */
.lg-metrics {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr));
  border: 1px solid var(--lg-border); border-radius: var(--lg-radius-md); background: var(--lg-bg-panel); }}
.lg-metric {{ padding: 14px 18px; border-left: 1px solid var(--lg-border); min-width: 0; }}
.lg-metric:first-child {{ border-left: 0; }}
.lg-metric .k {{ font-size: 12px; font-weight: 500; color: var(--lg-text-muted); white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis; }}
.lg-metric .v {{ font-size: 26px; font-weight: 500; color: var(--lg-text-primary);
  font-variant-numeric: tabular-nums; line-height: 1.3; margin-top: 2px; }}
.lg-metric .n {{ font-size: 12px; color: var(--lg-text-muted); font-variant-numeric: tabular-nums; }}
.lg-metric.critical .v {{ color: var(--lg-critical); }}
@media (max-width: 768px) {{
  [data-testid="stMainBlockContainer"] {{ padding-left: 16px; padding-right: 16px; padding-top: 3rem; }}
  .lg-metrics {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
  .lg-metric:nth-child(3) {{ border-left: 0; }}
  .lg-metric:nth-child(n+3) {{ border-top: 1px solid var(--lg-border); }}
  .lg-head h1 {{ font-size: 22px; }}
}}

/* severity + kind */
.lg-sev {{ font-size: 12px; font-weight: 560; white-space: nowrap; }}
.lg-sev.critical {{ color: var(--lg-critical); }}
.lg-sev.warning {{ color: var(--lg-warning); }}
.lg-sev.info {{ color: var(--lg-info); }}
.lg-kind {{ display: inline-block; font-size: 11.5px; color: var(--lg-text-secondary);
  border: 1px solid var(--lg-border); border-radius: var(--lg-radius-sm); padding: 0 6px; margin-left: 8px;
  line-height: 18px; }}

/* definition list */
.lg-dl {{ display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: 7px 18px; font-size: 13px;
  margin: 4px 0 0 0; }}
.lg-dl dt {{ color: var(--lg-text-muted); }}
.lg-dl dd {{ margin: 0; color: var(--lg-text-primary); font-variant-numeric: tabular-nums;
  overflow-wrap: anywhere; }}
.lg-mono {{ font-family: 'Geist Mono', Consolas, monospace; font-size: 12px; }}

/* empty state */
.lg-empty {{ padding: 28px 4px 12px 4px; }}
.lg-empty h3 {{ font-size: 16px; font-weight: 600; margin: 0 0 6px 0; color: var(--lg-text-primary); }}
.lg-empty p {{ font-size: 14px; color: var(--lg-text-secondary); margin: 0; max-width: 62ch; }}

/* inspector */
.lg-finding-title {{ font-size: 16px; font-weight: 600; color: var(--lg-text-primary); margin: 6px 0 4px 0;
  line-height: 1.35; }}
.lg-explain {{ font-size: 13.5px; color: var(--lg-text-secondary); margin: 0 0 10px 0; }}
.lg-action {{ font-size: 13px; color: var(--lg-text-primary); border-left: 2px solid var(--lg-accent);
  padding: 2px 0 2px 10px; margin: 6px 0 12px 0; }}
.lg-caption {{ font-size: 12px; color: var(--lg-text-muted); margin-top: 4px; }}
.lg-coords {{ width: 100%; table-layout: fixed; border-collapse: collapse; font-size: 12px;
  font-variant-numeric: tabular-nums; }}
.lg-coords td, .lg-coords th {{ padding: 4px 3px; border-bottom: 1px solid var(--lg-border); text-align: right;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.lg-coords td:first-child, .lg-coords th:first-child {{ width: 31%; }}
.lg-coords th {{ color: var(--lg-text-muted); font-weight: 500; }}
.lg-coords td:first-child, .lg-coords th:first-child {{ text-align: left; color: var(--lg-text-muted); }}

.st-key-findings-list [data-testid="stButton"] button {{
  justify-content: flex-start; text-align: left; min-height: 0; padding: 7px 10px;
  border-color: transparent; background: transparent;
}}
.st-key-findings-list [data-testid="stButton"] button:hover {{ background: var(--lg-bg-hover); }}
.st-key-findings-list [data-testid="stButton"] button[kind="primary"] {{
  background: var(--lg-accent-soft); border-color: var(--lg-accent); color: var(--lg-text-primary);
}}
.st-key-findings-list [data-testid="stButton"] p {{ font-size: 13px; line-height: 1.35; text-align: left; }}
[class*="st-key-fi_critical"] [data-testid="stIconMaterial"] {{ color: var(--lg-critical); }}
[class*="st-key-fi_warning"] [data-testid="stIconMaterial"] {{ color: var(--lg-warning); }}
[class*="st-key-fi_info"] [data-testid="stIconMaterial"] {{ color: var(--lg-info); }}
.st-key-canvas img {{ border-radius: var(--lg-radius-sm); }}
/* phones: Streamlit stacks the inspector columns; show the canvas first */
@media (max-width: 640px) {{
  [data-testid="stColumn"]:has(.st-key-canvas) {{ order: -1; }}
}}
/* image prev/next: icon-only visually, label kept for screen readers */
.st-key-imgnav [data-testid="stButton"] [data-testid="stMarkdownContainer"],
.st-key-imgnav [data-testid="stButton"] kbd {{
  position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap;
}}
.st-key-imgnav [data-testid="stButton"] button {{ padding-left: 10px; padding-right: 10px; }}
[data-testid="stDataFrame"] {{ font-variant-numeric: tabular-nums; }}
[data-testid="stExpander"] details {{ border-radius: var(--lg-radius-md); }}
</style>
"""


def inject_css() -> None:
    st.html(_css())


def page_header(title: str, description: str, context: str | None = None):
    """Title + description on the left; returns a right-aligned container for actions."""
    left, right = st.columns([3, 2], vertical_alignment="bottom")
    with left:
        ctx = f'<div class="lg-context">{context}</div>' if context else ""
        st.html(f'<div class="lg-head"><h1>{esc(title)}</h1><p>{esc(description)}</p>{ctx}</div>')
    actions = right.container(horizontal=True, horizontal_alignment="right", gap="small")
    return actions


def divider() -> None:
    st.html('<hr class="lg-rule">')


def section(title: str, sub: str | None = None) -> None:
    s = f'<p class="lg-sub">{esc(sub)}</p>' if sub else ""
    st.html(f'<div class="lg-section">{esc(title)}</div>{s}')


def metric_strip(items: list[tuple[str, str, str | None, str]]) -> None:
    """items: (label, value, note, css_class)."""
    cells = "".join(
        f'<div class="lg-metric {esc(cls)}"><div class="k">{esc(k)}</div><div class="v">{esc(v)}</div>'
        f'<div class="n">{esc(n) if n else "&nbsp;"}</div></div>'
        for k, v, n, cls in items
    )
    st.html(f'<div class="lg-metrics" role="group" aria-label="Summary">{cells}</div>')


def severity_html(sev: str) -> str:
    s = sev.lower()
    return f'<span class="lg-sev {esc(s)}">{SEVERITY_GLYPH.get(s, "")} {esc(s.capitalize())}</span>'


def severity_text(sev: str) -> str:
    s = str(sev).lower()
    return f"{SEVERITY_GLYPH.get(s, '')} {s.capitalize()}"


def kind_html(kind: str) -> str:
    return f'<span class="lg-kind">{esc(kind.capitalize())}</span>'


def dl(rows: list[tuple[str, str]], raw: bool = False) -> None:
    body = "".join(f"<dt>{esc(k)}</dt><dd>{v if raw else esc(v)}</dd>" for k, v in rows)
    st.html(f'<dl class="lg-dl">{body}</dl>')


def empty_state(title: str, text: str) -> None:
    st.html(f'<div class="lg-empty"><h3>{esc(title)}</h3><p>{esc(text)}</p></div>')


def is_dark() -> bool:
    return theme_type() == "dark"
