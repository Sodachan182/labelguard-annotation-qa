"""Detection metrics against an injected-error manifest.

Matching unit: ``(rule_id, target)``, where target is the annotation id or, for
image-level findings, the image id. A finding is a true positive only when the
expected rule fires on the expected object.

Findings on the corrupted copy that also occur on the untouched original are
*pre-existing*: they are neither true nor false positives for the injection
experiment, because the ground truth for the original labels is unknown. They
are reported separately and excluded from precision. Every remaining finding
that is not in the manifest is a false positive.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from labelguard.models import QualityIssue
from labelguard.validation.engine import RULES, all_rules


@dataclass
class Counts:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float | None:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else None

    @property
    def recall(self) -> float | None:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else None

    @property
    def f1(self) -> float | None:
        p, r = self.precision, self.recall
        if p is None or r is None:
            return None
        return 2 * p * r / (p + r) if p + r else 0.0

    def as_dict(self) -> dict:
        def rnd(v: float | None) -> float | None:
            return None if v is None else round(v, 4)

        return {
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
            "precision": rnd(self.precision),
            "recall": rnd(self.recall),
            "f1": rnd(self.f1),
        }


def issue_target(issue: QualityIssue) -> str:
    return issue.annotation_id or issue.image_id or issue.track_id or issue.source_location


def issue_keys(issues: Iterable[QualityIssue]) -> set[tuple[str, str]]:
    return {(i.rule_id, issue_target(i)) for i in issues}


def evaluate_findings(
    expected: Iterable[tuple[str, str]],
    findings: Iterable[QualityIssue],
    baseline: Iterable[QualityIssue] = (),
) -> dict:
    all_rules()
    exp = set(expected)
    found = list(findings)
    det = issue_keys(found)
    pre = issue_keys(baseline) - exp
    overall = Counts()
    by_kind: dict[str, Counts] = defaultdict(Counts)
    by_rule: dict[str, Counts] = defaultdict(Counts)
    for key in exp | (det - pre):
        rule = key[0]
        kind = RULES[rule].kind.value if rule in RULES else "unknown"
        field = "tp" if key in exp and key in det else ("fp" if key in det else "fn")
        for c in (overall, by_kind[kind], by_rule[rule]):
            setattr(c, field, getattr(c, field) + 1)
    titles = {(i.rule_id, issue_target(i)): i.title for i in found}
    return {
        "expected": len(exp),
        "detected_unique": len(det),
        "pre_existing_excluded": len(det & pre),
        "overall": overall.as_dict(),
        "by_kind": {k: v.as_dict() for k, v in sorted(by_kind.items())},
        "by_rule": {k: v.as_dict() for k, v in sorted(by_rule.items())},
        "false_negatives": [{"rule_id": r, "target": t} for r, t in sorted(exp - det)],
        "false_positives": [
            {"rule_id": r, "target": t, "title": titles.get((r, t), "")} for r, t in sorted(det - exp - pre)
        ],
    }
