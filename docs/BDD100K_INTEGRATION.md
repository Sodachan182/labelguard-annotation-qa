# BDD100K and CVAT integration

This document explains how LabelGuard is exercised on real driving data:
real BDD100K photographs → original BDD100K labels → COCO / CVAT formats →
(CVAT server, prepared) → LabelGuard validation → inspector → reports.

## Dataset and licence

- **Dataset:** BDD100K, *100K Images* package, **val** split, with the original per-image
  labels from `bdd100k_labels.zip` (2018 release, 10 detection classes:
  person, rider, car, truck, bus, train, motor, bike, traffic light, traffic sign).
- **Official source:** <https://github.com/bdd100k/bdd100k>; download page
  `doc/source/download.rst`; format `doc/source/format.rst`.
- **Licence:** BDD100K data licence
  (<https://github.com/bdd100k/bdd100k/blob/master/doc/source/license.rst>): use, copy,
  modify and distribute for educational, research and not-for-profit purposes, with the
  copyright notice "© 2018 The Regents of the University of California". Downloading the
  data means agreeing to it, so `labelguard bdd100k fetch` refuses to run without
  `--accept-license`.
- **LabelGuard's MIT licence does not apply to BDD100K content.** No BDD100K image, label
  file, corrupted copy or CVAT backup is committed (`data/` is git-ignored).

### Where the files come from (and why)

When this integration was built (23 Nov 2026) the official download host named in the
docs, `dl.cv.ethz.ch`, had no DNS record, and `bdd-data.berkeley.edu` served an expired
TLS certificate. Bypassing TLS was not an option, so the subset is read from the
Hugging Face redistribution **`dronefreak/BDD100K`**. Its dataset card states that the
files are byte-identical to Berkeley's `bdd100k_images_100k.zip` and `bdd100k_labels.zip`
and are redistributed under the BDD100K licence; it is **not an official release**.

Safeguards:

- pinned to revision `fea86dd9b24ea425d66b70e0fcb6ae0023b5dca5`;
- every file is verified against the checksum the Hub publishes for that path
  (SHA-256 for LFS files, git blob SHA-1 for small files) before it is kept;
- the provenance manifest records source, revision, seed, method and per-file checksums.

The official MD5 values apply to the full zips, which were not downloaded, so per-file
equality with Berkeley's originals rests on the redistributor's statement plus the pinned
checksums. If the official host returns, download `bdd100k_images_100k.zip` (5.3 GB) and
`bdd100k_labels.zip`, check the published MD5s and point `--data` at the extracted folder
layout.

### Label release caveat

The *Detection 2020* labels (`det_20`, re-checked) were not available from a reachable
source. This was re-checked in the final audit: the official hosts were still unreachable,
and none of 120 BDD100K-related Hugging Face dataset repositories listed a `det_20`,
`det_val` or `det_train` file. The 2018 per-image labels are used instead; the redistributor reports that they
agree with the 2018 combined file on `val`. LabelGuard's adapter also reads `det_20`
files (`det_val.json`) and detects that ontology automatically.

## Disk and network budget

| Item | Size |
|---|---|
| Val metadata tables used for sampling (2 files) | 16.7 MB |
| Smoke subset (20 images + labels) | 1.5 MB |
| Standard subset (100 images + labels) | 7.4 MB |
| Extended subset (500 images, optional, not run) | ≈ 37 MB estimated |

The 5.3 GB image package and the 1.8 TB video collection are never downloaded.

## Subset preparation

```powershell
labelguard bdd100k fetch --profile smoke --accept-license
```

```powershell
labelguard bdd100k fetch --profile standard --accept-license
```

Sampling is deterministic (seed 1729) over the 10,000 val images:

1. one image per class, rarest first (train, motor, rider, bike, bus, truck, person,
   traffic light, traffic sign, car);
2. one crowded scene (among the five with most boxes) and one sparse scene;
3. one image for each not-yet-covered value of `timeofday`, `weather` and `scene`;
4. the rest round-robin over (timeofday, weather, scene) strata.

Metadata values are used exactly as published, including `undefined`. After download,
each label file's `name` is checked against its image and each image's size is read from
its header (all 1280 × 720). Output: `data/bdd100k/<profile>/{images,labels,manifest.json}`.
A copy of the selection (file names, checksums, reasons) is in `benchmarks/bdd100k/`.

## Annotation format conversion

`box2d` corners are inclusive pixel indices. Following Scalabel's `box2d_to_bbox`:

| Target | Conversion |
|---|---|
| COCO | `[x1, y1, x2 − x1 + 1, y2 − y1 + 1]` |
| CVAT XML | `xtl = x1, ytl = y1, xbr = x2 + 1, ybr = y2 + 1` |
| LabelGuard internal | `[x1, y1, x2 + 1, y2 + 1]`, original kept in `bbox_source` |

`poly2d` objects (lane markings, drivable areas) are not detection labels; they are
counted and reported as "not validated" (standard subset: 551 lane, 148 area), never
dropped silently. The conversions are verified by re-parsing their output and comparing
it with the original box by box (`labelguard.benchmark.compare`):

| Subset | COCO | CVAT XML |
|---|---|---|
| Smoke | 418 / 418 matched, max corner difference 0 px | 418 / 418, 0.00005 px (4-decimal output) |
| Standard | 1,643 / 1,643, 0 px | 1,643 / 1,643, 0.00005 px |

Image names, image sizes, category counts and per-image box associations were identical.

## Injected errors

`labelguard.benchmark.corrupt` writes a **separate copy** of the labels
(`data/bdd100k/derived/<profile>/corrupted/labels.json`) and a manifest with image,
original and modified annotation id, error type, expected rule, original value, corrupted
value and seed. Pixels and the original files are never touched. Nine error types, three
injections each (seed 7): out-of-bounds box, zero-area box, duplicate, unknown category,
extreme aspect ratio, non-finite coordinate, record for an image absent from the subset,
high-IoU box with a conflicting class, and a schema-violating `occluded` value.
Error type 10 (video track anomaly) was **not** done: no BDD100K MOT data was downloaded,
and tracks are not synthesised from still images.

## CVAT (prepared, not yet executed)

The development machine had no Docker and only ~17 GB free disk, so the CVAT stack was not
installed. Everything needed is in the repository:

| Script | Purpose |
|---|---|
| `scripts/start-cvat.ps1` | Clone CVAT at a pinned tag into `%USERPROFILE%\labelguard-cvat` (outside this repo), check disk space, `docker compose -p labelguard-cvat up -d` on localhost, wait for `/api/server/about`. Creating the admin user is an interactive step. |
| `scripts/stop-cvat.ps1` | `docker compose -p labelguard-cvat stop`: only this stack, data and volumes kept. |
| `scripts/cvat_bdd100k_e2e.py` | With `cvat-sdk`: create or reuse project "LabelGuard — BDD100K QA Benchmark", Task A (original) and Task B (corrupted copy); upload the real images; import COCO; read back shape counts; export "CVAT for images 1.1" and "COCO 1.0"; parse the exports with LabelGuard; compare with the reference; validate. Credentials come from `CVAT_USER` and `CVAT_PASSWORD` and are never printed. |
| `scripts/test-bdd100k.ps1` | Level 2 tests and benchmark; add `-WithCvat` for level 3. |

**Version pinning (checked 23 Nov 2026):** the latest CVAT release is **v2.83.0**
(12 Nov 2026), and `start-cvat.ps1` defaults to it. Install the matching SDK with
`pip install -e ".[cvat]"` (`cvat-sdk==2.83.0`). Every SDK call the script makes was
checked against the installed 2.83.0 API: `make_client`, `projects.list/create`,
`tasks.list`, `tasks.create_from_data(spec, resources, resource_type=…,
annotation_path=…, annotation_format=…)` (which defaults `image_quality` to 70),
`Task.fetch/get_annotations/export_dataset(format_name, filename, include_images=…)`.

**Network exposure:** CVAT's stock compose publishes Traefik on all interfaces.
`start-cvat.ps1` writes a compose override, outside the CVAT checkout's tracked files,
that rebinds ports 8080/8090 to `127.0.0.1` (needs Docker Compose ≥ 2.24 for `!override`).
This has not been exercised on a real run yet.

**What is tested without a server:** `tests/test_cvat_e2e.py` runs the whole orchestration
against a **mock** client that mimics the SDK surface and exports the uploaded COCO file
unchanged. It checks exact Task A round trips in both export formats, the per-rule
injected-error comparison for Task B, safe extraction of export archives, and idempotent
re-runs (project and tasks are reused). A mock models an ideal server: a real CVAT may
clip out-of-bounds boxes or drop zero-area shapes on import, and only a real run can show
that.

**Task B scoring:** CVAT renumbers objects, so the BDD100K object ids used by the local
benchmark are not available after export. Task B compares *counts per rule*: expected
injections versus findings on the export and on the uploaded reference. Only the five
injection types COCO can carry are scored (out of bounds, zero area, duplicate, extreme
aspect, class overlap). Non-finite coordinates, unknown categories and schema-violating
attributes are dropped or flattened by the conversion and listed in `task_b_conversion`.

## Reproduce

```powershell
.\scripts\test-bdd100k.ps1 -Profile smoke -AcceptLicense
```

or step by step: `labelguard bdd100k fetch …`, `labelguard bdd100k benchmark --profile smoke`,
then open the app and choose **Datasets → Load BDD100K sample**.

## Known limitations

- 20 and 100 images; the 500-image profile exists but was not run.
- 2018 labels rather than Detection 2020.
- Unofficial (licence-permitted) redistribution, pinned and checksum-verified.
- No CVAT server round trip yet; no real video tracks.
