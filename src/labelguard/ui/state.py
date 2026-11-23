"""Session state: loaded datasets, active selection and persisted settings.

Uploaded files are copied into a per-session temporary folder; originals on the
user's disk are never opened for writing. Settings persist to
``~/.labelguard/settings.json``.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st

from labelguard.config import ValidationConfig
from labelguard.models import Dataset, QualityIssue, QualityReport
from labelguard.parsers.archive import load_path
from labelguard.validation.engine import validate

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_ROOT = Path(os.environ.get("LABELGUARD_DATA", PROJECT_ROOT / "data"))
SETTINGS_FILE = Path.home() / ".labelguard" / "settings.json"

DEFAULT_PREFS: dict[str, Any] = {
    "overlay_mode": "all",
    "show_labels": True,
    "show_ids": False,
    "zoom_to_selection": False,
    "images_with_findings_only": False,
    "canvas_resolution": 1600,
    # Real-data sample to reload when a new browser session starts (None = start empty).
    "restore_bdd_profile": None,
}


@dataclass
class Entry:
    id: str
    dataset: Dataset
    source: str
    origin: dict[str, Any]
    imported_at: datetime = field(default_factory=datetime.now)
    report: QualityReport | None = None
    files: int = 0
    error: str | None = None

    @property
    def validation_status(self) -> str:
        if self.report is None:
            return "Not validated"
        return f"Validated ({self.report.profile})"


def _load_settings() -> tuple[ValidationConfig, dict[str, Any]]:
    try:
        raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        cfg = ValidationConfig.model_validate(raw.get("validation", {}))
        prefs = {**DEFAULT_PREFS, **{k: v for k, v in raw.get("display", {}).items() if k in DEFAULT_PREFS}}
        return cfg, prefs
    except (OSError, ValueError):
        return ValidationConfig(), dict(DEFAULT_PREFS)


def save_settings() -> str | None:
    """Write settings; returns an error message or None."""
    try:
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {"validation": config().model_dump(mode="json"), "display": prefs()}
        tmp = SETTINGS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(SETTINGS_FILE)
        return None
    except OSError as exc:
        return f"Settings could not be saved to {SETTINGS_FILE}: {exc}"


def init() -> None:
    ss = st.session_state
    if "lg_datasets" not in ss:
        ss.lg_datasets = {}
        ss.lg_active = None
        ss.lg_selected_issue = None
        ss.lg_selected_annotation = None
        ss.lg_inspector_image = None
        ss.lg_config, ss.lg_prefs = _load_settings()
        cleanup_stale_sessions()
        ss.lg_workdir = Path(tempfile.mkdtemp(prefix="labelguard-session-"))
        profile = ss.lg_prefs.get("restore_bdd_profile")
        if profile and profile in bdd_subsets():
            load_bdd_sample(profile, remember=False)


SESSION_MAX_AGE_S = 24 * 3600


def cleanup_stale_sessions(base: Path | None = None, max_age_s: float = SESSION_MAX_AGE_S) -> int:
    """Delete LabelGuard session folders older than ``max_age_s`` (copies of uploads only)."""
    import time

    base = Path(base or tempfile.gettempdir())
    removed = 0
    for d in base.glob("labelguard-session-*"):
        try:
            if d.is_dir() and time.time() - d.stat().st_mtime > max_age_s:
                shutil.rmtree(d, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    return removed


def new_workdir(base: Path, prefix: str) -> Path:
    """A fresh, never-reused folder, so two imports can never share extracted files."""
    base.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=f"{prefix}-", dir=base))


def entries() -> dict[str, Entry]:
    return st.session_state.lg_datasets


def active() -> Entry | None:
    ss = st.session_state
    e = ss.lg_datasets.get(ss.lg_active)
    if e is None and ss.lg_datasets:
        ss.lg_active = next(iter(ss.lg_datasets))
        e = ss.lg_datasets[ss.lg_active]
    return e


def set_active(entry_id: str) -> None:
    ss = st.session_state
    if ss.lg_active != entry_id:
        ss.lg_active = entry_id
        clear_selection()
        ss.lg_inspector_image = None


def config() -> ValidationConfig:
    return st.session_state.lg_config


def set_config(cfg: ValidationConfig) -> None:
    st.session_state.lg_config = cfg


def prefs() -> dict[str, Any]:
    return st.session_state.lg_prefs


def clear_selection() -> None:
    st.session_state.lg_selected_issue = None
    st.session_state.lg_selected_annotation = None


def select_issue(issue: QualityIssue) -> None:
    ss = st.session_state
    ss.lg_selected_issue = issue.issue_id
    ss.lg_selected_annotation = issue.annotation_id
    if issue.image_id:
        ss.lg_inspector_image = issue.image_id


def run_validation(entry: Entry, progress=None) -> QualityReport:
    entry.report = validate(entry.dataset, config(), progress=progress)
    return entry.report


def add_from_path(
    path: Path, source: str, images_dir: Path | None = None, origin: dict | None = None, validate_now: bool = True
) -> tuple[list[Entry], list[str]]:
    workdir = new_workdir(st.session_state.lg_workdir, "import")
    result = load_path(path, workdir=workdir, images_dir=images_dir)
    added = []
    for ds in result.datasets:
        entry = Entry(
            id=ds.id,
            dataset=ds,
            source=source,
            origin=origin or {"path": str(path), "images_dir": str(images_dir) if images_dir else None},
            files=result.image_files or len(ds.image_paths),
        )
        if validate_now:
            run_validation(entry)
        entries()[entry.id] = entry
        added.append(entry)
    if added:
        set_active(added[0].id)
    return added, result.errors


def save_uploads(files) -> Path:
    """Copy uploaded files into a fresh session folder (never touching originals)."""
    dest = new_workdir(st.session_state.lg_workdir, "upload")
    for f in files:
        name = Path(f.name).name  # drop any client-side path components
        (dest / name).write_bytes(f.getbuffer())
    return dest


def remove(entry_id: str) -> None:
    e = entries().pop(entry_id, None)
    if e and e.origin.get("session_copy"):
        shutil.rmtree(e.origin["session_copy"], ignore_errors=True)
    if st.session_state.lg_active == entry_id:
        st.session_state.lg_active = next(iter(entries()), None)
        clear_selection()


def reimport(entry: Entry) -> list[str]:
    origin = entry.origin
    remove(entry.id)
    _, errors = add_from_path(
        Path(origin["path"]), entry.source, Path(origin["images_dir"]) if origin.get("images_dir") else None, origin
    )
    return errors


# --------------------------------------------------------------------- real data


def bdd_subsets() -> list[str]:
    root = DATA_ROOT / "bdd100k"
    return [p for p in ("smoke", "standard", "extended") if (root / p / "labels").is_dir()]


def load_bdd_sample(profile: str, remember: bool = True) -> list[str]:
    root = DATA_ROOT / "bdd100k"
    images = root / profile / "images"
    errors: list[str] = []
    added, errs = add_from_path(root / profile / "labels", f"BDD100K val · {profile} subset", images)
    errors += errs
    for e in added:
        e.dataset.name = f"BDD100K {profile} — original labels"
    corrupted = root / "derived" / profile / "corrupted" / "labels.json"
    if corrupted.exists():
        added_c, errs = add_from_path(corrupted, f"BDD100K val · {profile} corrupted copy", images)
        errors += errs
        for e in added_c:
            e.dataset.name = f"BDD100K {profile} — corrupted copy"
    if added:
        set_active(added[0].id)
        if remember:
            prefs()["restore_bdd_profile"] = profile
            save_settings()
    return errors
