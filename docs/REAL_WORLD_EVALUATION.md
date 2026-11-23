# Real-world evaluation

All numbers below were produced by `labelguard bdd100k benchmark` on 23 Nov 2026
(Windows 11, Python 3.12.10, LabelGuard 1.0.0, profile `bdd100k_detection`, 33 rules).
Machine-readable results: `benchmarks/bdd100k/{smoke,standard}_results.json`.

## Data

| | Smoke | Standard |
|---|---:|---:|
| BDD100K val images (1280 × 720, all with pixels) | 20 | 100 |
| Detection boxes (original labels) | 418 | 1,643 |
| Non-detection objects reported, not validated (lane / drivable area) | 134 / 32 | 551 / 148 |
| car / traffic sign / traffic light / person | 199 / 83 / 63 / 42 | 934 / 300 / 229 / 101 |
| truck / bus / bike / rider / motor / train | 17 / 2 / 5 / 5 / 1 / 1 | 46 / 14 / 9 / 7 / 2 / 1 |
| Time of day: daytime / night / dawn-dusk / undefined | 9 / 5 / 5 / 1 | 42 / 31 / 26 / 1 |

## A. Original BDD100K labels

| | Smoke | Standard |
|---|---:|---:|
| Structural findings | 0 | 0 |
| Heuristic findings | 0 | 1 |
| Parse time | 42 ms | 146 ms |
| Validation time | 87 ms | 134 ms |
| Peak traced Python memory (parse + validate) | 3.7 MB | 8.3 MB |
| Slowest rules | BOX006 5.4 ms, BOX007 4.8 ms | BOX007 18.8 ms, BOX006 18.5 ms |

The one standard-subset finding is `BOX004` (suspiciously small box) on a `car` in image
`bf76fa8e-889c317d`: 7.6 × 4.7 px (area 36 px², just under the 36 px² default). In the
Inspector, zoomed to the selection, it sits on a distant vehicle on a highway under an
overpass. It looks like a plausible distant car rather than a stray click, so it is a
**false-positive candidate under default thresholds**, recorded for manual review and not
counted as a confirmed error or a confirmed false positive. The original labels are not
assumed to be perfect. No rule found a structural defect in these 1,643 boxes.

The duplicate and conflict rules (`BOX006`, `BOX007`) are the slowest because they compute
per-image IoU matrices. They are vectorised with NumPy and stay well under 20 ms for
100 images, so no further optimisation was needed at this scale.

## B. Injected errors on a copy of the real labels

27 injections (9 types × 3, seed 7) into a copy of the same labels. Findings that also
appear on the untouched original are *pre-existing* and excluded from precision (1 on the
standard subset, the `BOX004` above).

| | Smoke | Standard |
|---|---:|---:|
| Structural (deterministic) TP / FP / FN | 18 / 0 / 0 | 18 / 0 / 0 |
| Heuristic TP / FP / FN | 9 / 0 / 0 | 9 / 0 / 0 |
| Precision / recall / F1 | 1.0 / 1.0 / 1.0 | 1.0 / 1.0 / 1.0 |

Expected rule per error type: out of bounds → BOX003, zero area → BOX001,
duplicate → BOX006, unknown category → INT004, extreme aspect → BOX005, non-finite
coordinate → INT002, absent image → INT009, conflicting class overlap → BOX007,
invalid `occluded` value → INT007.

### How to read this

- Matching is strict: the expected rule must fire on the expected object
  (`<image>:<object id>`), so a finding on the right box from the wrong rule is both an FP
  and an FN.
- The injections were written with the rules in mind. A perfect score means every rule
  fires on real geometry and the corruptions do not trigger collateral findings in crowded
  real scenes. It does **not** measure how many naturally occurring labelling mistakes
  LabelGuard would catch; that would need an independently audited set of real errors.

### Problems this evaluation found and fixed

The first real-data runs exposed defects that synthetic fixtures had not:

1. BDD100K per-image labels restart object ids at 0 in every file, so global id
   uniqueness produced about 1,580 false `INT003` findings. Ids are now scoped per image.
2. Per-image label files store `name` without `.jpg`, so no image was matched and sizes
   were silently assumed. The lookup now tries image extensions, and an assumed size is
   reported.
3. A provenance `manifest.json` with an `images` key was misread as COCO; COCO detection
   is now stricter.
4. Combined label files are JSON arrays, which the format sniffer rejected.
5. The corruption script copied an object from an already-corrupted record, creating an
   unintended second defect (1 FP on smoke). It now copies from the untouched originals.

## Visual verification

The overlay renderer was checked on the most crowded image in the standard subset
(`ca1543ec-6ad48f6e`, 61 boxes): boxes align with the cars, pedestrians, cyclist and
traffic lights at 1:1 scale and in zoomed crops. Browser captures covered both themes at
1920, 1440, 1366, 1024 and 390 px (60 captures, no horizontal overflow, no exceptions).

## Not done

CVAT server round trip (prepared, not executed), the 500-image profile, and real video
tracks (BDD100K MOT). See [BDD100K_INTEGRATION.md](BDD100K_INTEGRATION.md).

## Reproduce

```powershell
labelguard bdd100k fetch --profile standard --accept-license
```

```powershell
labelguard bdd100k benchmark --profile standard
```
