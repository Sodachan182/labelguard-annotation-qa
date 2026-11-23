# BDD100K benchmark results (aggregate only)

- `smoke_results.json`, `standard_results.json`: metrics written by
  `labelguard bdd100k benchmark`, covering counts, timings, conversion checks and
  injected-error precision and recall. They contain no images and no label geometry.
- `smoke_selection.json`, `standard_selection.json`: which BDD100K val files were sampled,
  why, and their verified checksums, so the same subset can be fetched again. They are
  non-sensitive metadata.

BDD100K images and labels are **not** in this repository. They are subject to the
[BDD100K license](https://github.com/bdd100k/bdd100k/blob/master/doc/source/license.rst),
© 2018 The Regents of the University of California. See
[docs/BDD100K_INTEGRATION.md](../../docs/BDD100K_INTEGRATION.md).
