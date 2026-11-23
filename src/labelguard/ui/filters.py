"""Pure issue-filtering logic shared by the Issues page and tests."""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd


def filter_issues(
    df: pd.DataFrame,
    severities: Iterable[str] = (),
    kinds: Iterable[str] = (),
    rules: Iterable[str] = (),
    categories: Iterable[str] = (),
    image: str | None = None,
    query: str = "",
) -> pd.DataFrame:
    """Empty selections mean 'no filter'. Search is case-insensitive over text fields."""
    out = df
    sev, knd, rl, cat = (set(map(str.lower, severities)), set(map(str.lower, kinds)), set(rules), set(categories))
    if sev:
        out = out[out["severity"].str.lower().isin(sev)]
    if knd:
        out = out[out["kind"].str.lower().isin(knd)]
    if rl:
        out = out[out["rule_id"].isin(rl)]
    if cat:
        out = out[out["category"].fillna("").isin(cat)]
    if image:
        out = out[(out["image_id"] == image) | (out["image_name"] == image)]
    q = query.strip().lower()
    if q:
        hay = (
            out[["title", "description", "annotation_id", "image_name", "rule_name", "rule_id", "category"]]
            .fillna("")
            .astype(str)
            .agg(" ".join, axis=1)
            .str.lower()
        )
        out = out[hay.str.contains(q, regex=False)]
    return out
