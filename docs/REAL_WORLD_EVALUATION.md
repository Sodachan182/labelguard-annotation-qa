# Real-world evaluation

All numbers were produced by the commands at the end of this page on 23 Nov 2026
(Windows 11, Python 3.12.10, LabelGuard 1.0.0, profile `bdd100k_detection`, 33 rules) and
re-run during the final audit with identical outcomes. Machine-readable results:
`benchmarks/bdd100k/{smoke,standard}_results.json`.

## Four kinds of evidence (do not mix them)

| | What it shows | Status |
|---|---|---|
| 1. Structural validation on original labels | Format and geometry defects in real BDD100K labels | Run: 0 defects in 1,643 boxes |
| 2. Heuristic anomaly detection on original labels | Suspicious but valid boxes for a person to judge | Run: 1 finding at default thresholds |
| 3. Injected-error evaluation | Each rule fires on real geometry, without collateral noise | Run: 27/27 detected, 0 false positives |
| 4. Independently reviewed real annotations | How often heuristic findings are real mistakes | Prepared: 40 candidates exported, **0 reviewed by a person yet** |

Only (4) could measure how useful the heuristics are on real data, and it needs human
decisions. Nothing in this repository fills those decisions automatically.

## Data

| | Smoke | Standard |
|---|---:|---:|
| BDD100K val images (1280 × 720, all with pixels) | 20 | 100 |
| Detection boxes (original 2018 per-image labels) | 418 | 1,643 |
| Non-detection objects reported, not validated (lane / drivable area) | 134 / 32 | 551 / 148 |
| car / traffic sign / traffic light / person | 199 / 83 / 63 / 42 | 934 / 300 / 229 / 101 |
| truck / bus / bike / rider / motor / train | 17 / 2 / 5 / 5 / 1 / 1 | 46 / 14 / 9 / 7 / 2 / 1 |
| Time of day: daytime / night / dawn-dusk / undefined | 9 / 5 / 5 / 1 | 42 / 31 / 26 / 1 |

Provenance is verified file by file against the pinned redistribution
(`tests/test_realdata.py::test_manifest_checksums_match_files`); every image is 1280 × 720
read from its header, and every label file names its image.

**Detection 2020 labels:** not used. During the audit, the official hosts were still
unreachable (no DNS for `dl.cv.ethz.ch`, expired TLS on `bdd-data.berkeley.edu`), and none
of 120 BDD100K-related Hugging Face dataset repositories contained a `det_20` / `det_val`
file in its listing. The benchmark therefore stays on the 2018 labels, and versions are
never mixed. The adapter already reads `det_20` files if they become available.

## 1 and 2. Original labels

| | Smoke | Standard |
|---|---:|---:|
| Structural findings | 0 | 0 |
| Heuristic findings | 0 | 1 |
| Parse time | 44 ms | 163 ms |
| Validation time | 77 ms | 131 ms |
| Peak traced Python memory (parse + validate) | 3.3 MB | 8.1 MB |
| Slowest rules | BOX006 4.6 ms, BOX007 4.3 ms | BOX006 20.5 ms, BOX007 20.4 ms |

The single standard-subset finding is `BOX004` on a `car` in `bf76fa8e-889c317d`
(7.6 × 4.7 px, 36 px², just under the default minimum). It is a **review candidate**, not a
confirmed error and not a confirmed false positive. Timings vary by about ±15 % between
runs on the same machine.

## 3. Injected errors on a copy of the real labels

27 injections (9 types × 3, seed 7) in a separate copy; findings already present on the
original are excluded as pre-existing (1 on standard).

| | Smoke | Standard |
|---|---:|---:|
| Structural TP / FP / FN | 18 / 0 / 0 | 18 / 0 / 0 |
| Heuristic TP / FP / FN | 9 / 0 / 0 | 9 / 0 / 0 |
| Precision / recall / F1 | 1.0 / 1.0 / 1.0 | 1.0 / 1.0 / 1.0 |

Matching is strict (`rule id`, `<image>:<object id>`). The injections were written with
the rules in mind, so this is a correctness check of the implementation on real scenes,
**not** an estimate of how many naturally occurring mistakes LabelGuard finds.

## 4. Human review set (prepared, pending)

```powershell
labelguard bdd100k review-export --profile standard
```

This command runs the rules on the original standard labels with *review sensitivity*
thresholds: minimum area 150 px², minimum side 8 px, aspect ratio 6, duplicate IoU 0.7,
conflict IoU 0.6. It then writes `data/reviews/standard/review_sheet.csv` plus one zoomed
crop per candidate on the real image. The current export has **40 candidates**: 39
`BOX004` small boxes (27 traffic lights, 10 traffic signs, 2 cars) and 1 `BOX005`
extreme aspect ratio. No duplicate or conflicting-class candidates appeared at these
thresholds.

A reviewer fills `decision` (`error`, `acceptable`, `unsure`), `reviewer` and `notes`, then:

```powershell
labelguard bdd100k review-summary --profile standard
```

The summary counts only rows a person decided and reports the rest as pending. Its error
rate is `error ÷ (error + acceptable)`. At the time of writing: 40 candidates, 0 reviewed,
**no error rate published**. The crops contain BDD100K imagery and stay in the git-ignored
`data/` folder.

## Problems the real data exposed

First pass:
1. Per-image BDD100K ids restart at 0 per file, which produced about 1,580 false `INT003`
   findings. Ids are now scoped per image.
2. Label `name` values have no `.jpg`, so no image matched and sizes were silently assumed.
   Fixed, and assumed sizes are now reported.
3. A provenance `manifest.json` was misread as COCO.
4. Combined label files are JSON arrays, which the sniffer rejected.
5. The corruption script copied an already-corrupted object, causing 1 FP. It now copies
   from the originals.

Final audit:

6. Comparing BDD100K labels (`name` without extension) with CVAT/COCO exports
   (`x.jpg`) would have reported every image as missing in the CVAT round trip. Matching
   now uses the file stem.
7. Inspector: picking an image in the dropdown was silently undone on the next rerun.
8. After an upload or sample load, the sidebar selector switched the app back to the
   previous dataset.

Each has a regression test.

## Not done

- CVAT server round trip (scripted and mock-tested, not run against a server).
- The 500-image profile.
- Real video tracks (BDD100K MOT).
- Human review decisions.
- Detection 2020 labels.

## Reproduce

```powershell
labelguard bdd100k fetch --profile standard --accept-license
```

```powershell
labelguard bdd100k benchmark --profile standard
```

```powershell
python -m pytest -m realdata
```
