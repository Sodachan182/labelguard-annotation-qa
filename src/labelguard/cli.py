"""LabelGuard command-line interface.

Exit codes (stable, for CI pipelines):
    0  no finding at or above the --fail-on severity
    1  findings at or above --fail-on were found
    2  the input could not be read or parsed
"""

from __future__ import annotations

import json
import sys
from enum import StrEnum
from pathlib import Path

import typer

from labelguard import __version__
from labelguard.analytics.statistics import quality_score
from labelguard.config import PROFILES, ValidationConfig
from labelguard.models import QualityReport, Severity
from labelguard.parsers.archive import load_path
from labelguard.reports import to_csv, to_json, to_xlsx
from labelguard.validation.engine import all_rules, validate

app = typer.Typer(
    name="labelguard",
    help="Offline quality checks for CVAT and COCO annotation datasets.",
    no_args_is_help=True,
    add_completion=False,
)


class FailOn(StrEnum):
    critical = "critical"
    warning = "warning"
    info = "info"
    never = "never"


class OutputFormat(StrEnum):
    table = "table"
    json = "json"


class ReportFormat(StrEnum):
    json = "json"
    csv = "csv"
    xlsx = "xlsx"


def _config(profile: str, config: Path | None) -> ValidationConfig:
    if config is not None:
        cfg = ValidationConfig.from_file(config)
        return cfg if profile == "general_detection" else cfg.model_copy(update={"profile": profile})
    return ValidationConfig.for_profile(profile)


def _load(path: Path, cfg: ValidationConfig):
    if not path.exists():
        typer.secho(f"error: {path} does not exist", err=True, fg="red")
        raise typer.Exit(2)
    result = load_path(path)
    for err in result.errors:
        typer.secho(f"error: {err}", err=True, fg="red")
    if not result.datasets:
        raise typer.Exit(2)
    return [(ds, validate(ds, cfg)) for ds in result.datasets]


def _exit_code(reports: list[QualityReport], fail_on: FailOn) -> int:
    if fail_on == FailOn.never:
        return 0
    limit = Severity(fail_on.value).rank
    return 1 if any(i.severity.rank <= limit for r in reports for i in r.issues) else 0


def _print_table(ds, report: QualityReport, limit: int) -> None:
    score = quality_score(report)
    typer.secho(f"\n{ds.name}", bold=True)
    typer.echo(
        f"  {ds.source_format.label}  |  {report.image_count} images/frames  |  "
        f"{report.annotation_count} annotations  |  profile {report.profile}"
    )
    c, w, i = (report.count(s) for s in Severity)
    typer.echo(
        f"  {len(report.issues)} findings: {c} critical, {w} warning, {i} info"
        + (f"  |  quality score {score:.1f}" if score is not None else "")
    )
    for warn in ds.parse_warnings:
        typer.secho(f"  note: {warn}", fg="yellow")
    colors = {Severity.CRITICAL: "red", Severity.WARNING: "yellow", Severity.INFO: "blue"}
    for issue in report.issues[:limit]:
        where = issue.annotation_id or issue.image_id or issue.source_location
        typer.echo("  ", nl=False)
        typer.secho(f"{issue.severity.label:<8}", fg=colors[issue.severity], nl=False)
        typer.echo(f" {issue.rule_id}  {where:<14}  {issue.title}")
    if len(report.issues) > limit:
        typer.echo(f"  … {len(report.issues) - limit} more (use --limit or 'labelguard report')")


@app.command()
def scan(
    path: Path = typer.Argument(..., help="Annotation file (.xml/.json), directory or .zip archive."),
    profile: str = typer.Option("general_detection", "--profile", "-p", help="Rule profile."),
    config: Path | None = typer.Option(None, "--config", "-c", help="Validation config JSON."),
    fail_on: FailOn = typer.Option(FailOn.critical, "--fail-on", help="Severity that makes the exit code 1."),
    output: OutputFormat = typer.Option(OutputFormat.table, "--output", "-o", help="Console output format."),
    limit: int = typer.Option(25, "--limit", help="Findings to print per dataset (table output)."),
) -> None:
    """Validate a dataset and print a summary."""
    if profile not in PROFILES:
        typer.secho(f"error: unknown profile '{profile}' ({', '.join(PROFILES)})", err=True, fg="red")
        raise typer.Exit(2)
    cfg = _config(profile, config)
    results = _load(path, cfg)
    if output == OutputFormat.json:
        payload = [json.loads(to_json(r)) for _, r in results]
        typer.echo(json.dumps(payload if len(payload) > 1 else payload[0], indent=2))
    else:
        for ds, report in results:
            _print_table(ds, report, limit)
    raise typer.Exit(_exit_code([r for _, r in results], fail_on))


@app.command()
def report(
    path: Path = typer.Argument(..., help="Annotation file, directory or .zip archive."),
    format: ReportFormat = typer.Option(ReportFormat.json, "--format", "-f", help="Report format."),
    out: Path | None = typer.Option(None, "--out", help="Output file or folder (default: ./labelguard_reports)."),
    profile: str = typer.Option("general_detection", "--profile", "-p"),
    config: Path | None = typer.Option(None, "--config", "-c"),
) -> None:
    """Write a full report (JSON, CSV or XLSX) for each dataset found."""
    cfg = _config(profile, config)
    results = _load(path, cfg)
    target = out or Path("labelguard_reports")
    written = []
    for ds, rep in results:
        stem = Path(ds.name).stem.replace("/", "_") or "dataset"
        dest = target if (out and out.suffix and len(results) == 1) else target / f"{stem}_{ds.id[-8:]}.{format.value}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        if format == ReportFormat.json:
            dest.write_text(to_json(rep), encoding="utf-8")
        elif format == ReportFormat.csv:
            dest.write_text(to_csv(rep), encoding="utf-8-sig")
        else:
            dest.write_bytes(to_xlsx(rep, ds))
        written.append(dest)
        typer.echo(f"{dest}  ({len(rep.issues)} findings)")


@app.command()
def rules(
    profile: str = typer.Option(None, "--profile", "-p", help="Show only rules active in this profile."),
) -> None:
    """List validation rules."""
    active = None
    if profile:
        from labelguard.validation.engine import active_rules

        active = {r.id for r in active_rules(ValidationConfig.for_profile(profile))}
    for r in all_rules():
        if active is not None and r.id not in active:
            continue
        typer.echo(f"{r.id}  {r.severity.value:<8} {r.kind.value:<10} {r.name}")


@app.command()
def profiles() -> None:
    """List validation profiles."""
    for p in PROFILES.values():
        typer.secho(p.id, bold=True, nl=False)
        typer.echo(f"  {p.name}: {p.description}")


bdd = typer.Typer(help="Real-data workflow on a BDD100K validation subset.", no_args_is_help=True)
app.add_typer(bdd, name="bdd100k")


class SubsetProfile(StrEnum):
    smoke = "smoke"
    standard = "standard"
    extended = "extended"


@bdd.command("fetch")
def bdd_fetch(
    profile: SubsetProfile = typer.Option(
        SubsetProfile.smoke, "--profile", help="smoke=20, standard=100, extended=500 images."
    ),
    data: Path = typer.Option(Path("data/bdd100k"), "--data", help="Local, git-ignored data folder."),
    seed: int = typer.Option(1729, "--seed"),
    accept_license: bool = typer.Option(
        False, "--accept-license", help="Confirm you accept the BDD100K data license (research/educational use)."
    ),
) -> None:
    """Download and checksum-verify a small BDD100K val subset (images + original labels)."""
    from labelguard.benchmark.bdd100k_source import LICENSE_NOTICE, build_subset

    if not accept_license:
        typer.echo(LICENSE_NOTICE)
        typer.secho("Re-run with --accept-license to confirm and download.", fg="yellow")
        raise typer.Exit(2)
    out = build_subset(data, profile.value, seed)
    typer.echo(f"Subset written to {out}")


@bdd.command("benchmark")
def bdd_benchmark(
    profile: SubsetProfile = typer.Option(SubsetProfile.smoke, "--profile"),
    data: Path = typer.Option(Path("data/bdd100k"), "--data"),
    seed: int = typer.Option(7, "--seed", help="Corruption seed."),
    per_type: int = typer.Option(3, "--per-type", help="Injections per error type."),
    output: OutputFormat = typer.Option(OutputFormat.table, "--output", "-o"),
) -> None:
    """Validate original labels, verify COCO/CVAT conversions and score injected errors."""
    from labelguard.benchmark.runner import run_benchmark

    try:
        res = run_benchmark(data, profile.value, seed=seed, per_type=per_type)
    except FileNotFoundError as exc:
        typer.secho(f"error: {exc}", err=True, fg="red")
        raise typer.Exit(2) from exc
    if output == OutputFormat.json:
        typer.echo(json.dumps(res, indent=2))
        return
    d, o, inj = res["dataset"], res["original"], res["injected_errors"]
    typer.echo(f"{d['images']} images, {d['annotations']} boxes ({profile.value})")
    typer.echo(
        f"Original labels: {o['findings']} findings {o['by_rule']}  "
        f"parse {o['timing_ms']['parse']} ms, validate {o['timing_ms']['validate']} ms"
    )
    for name, conv in res["conversions"].items():
        c = conv["comparison"]
        typer.echo(
            f"{name:<9} round trip: matched {c['matched_boxes']}/{c['reference_boxes']}, "
            f"max corner delta {c['max_abs_corner_delta_px']} px, identical={c['identical_within_tolerance']}"
        )
    e = inj["evaluation"]
    typer.echo(
        f"Injected {inj['injections']} errors: TP {e['overall']['tp']}  FP {e['overall']['fp']}  "
        f"FN {e['overall']['fn']}  precision {e['overall']['precision']}  recall {e['overall']['recall']}"
    )
    for kind, c in e["by_kind"].items():
        typer.echo(f"  {kind:<10} TP {c['tp']:>3}  FP {c['fp']:>3}  FN {c['fn']:>3}")


def version_callback(value: bool) -> None:
    if value:
        typer.echo(f"labelguard {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(False, "--version", callback=version_callback, is_eager=True),
) -> None:
    """LabelGuard annotation QA."""


if __name__ == "__main__":  # pragma: no cover
    sys.exit(app())
