# Five-minute demo

**Setup:** `labelguard bdd100k fetch --profile standard --accept-license`, then
`labelguard bdd100k benchmark --profile standard`, then start the app
(`START_LABELGUARD.bat`). Load **Datasets → BDD100K standard → Load BDD100K sample**.

**0:00 Problem (30 s).** "Label mistakes such as boxes off the image, duplicates and labels
outside the ontology are cheap to find and expensive to train on. LabelGuard finds the
mechanical ones and makes the suspicious ones quick to review. It works offline on CVAT,
COCO and BDD100K."

**0:30 Real data (45 s).** Overview: 100 real BDD100K val images, 1,643 original boxes,
class distribution dominated by cars, signs and lights. "These are the original labels.
LabelGuard found zero structural defects and one heuristic warning."

**1:15 Honest heuristics (45 s).** Inspector opens on that finding: an 8 × 5 px car. Turn on
*Zoom to selection*: it is a distant car under an overpass. "Heuristic means a human
decides. This one is probably fine, which is why it is a warning and not an error."

**2:00 Injected errors (60 s).** Switch the active dataset to *corrupted copy*. Issues
page: 28 findings. Filter **Structural**, then search "ambulance" and open it in the
Inspector. Press → to walk to the car/truck overlap (IoU 0.97) and point at the
coordinate table: source `box2d` (inclusive) next to the normalized corners.

**3:00 Engineering (60 s).** Show `docs/REAL_WORLD_EVALUATION.md`: 27/27 injected errors
found, 0 false positives, COCO and CVAT round trips exact on 1,643 real boxes, 280 ms to
parse and validate 100 images. Mention the five bugs the real data exposed (per-image id
scope, extension-less names, and others) and why synthetic fixtures alone would have
missed them.

**4:00 Pipelines (45 s).** Terminal: `labelguard scan … --fail-on critical` returns exit
code 1 on the corrupted copy; Reports page downloads the Excel workbook.

**4:45 Close (15 s).** "Deterministic, offline and tested on real data. Next: run the
prepared CVAT round trip and add real video tracks."
