# Security

| Threat | Mitigation |
|---|---|
| XML entity expansion, external entities, DTDs | `defusedxml` with `forbid_dtd=True`; rejected with a clear error (tested). |
| ZIP path traversal, absolute paths, drive letters | Every member name is checked before anything is written; extraction target must stay inside a fresh temp folder (tested). |
| ZIP symlinks | Members with symlink mode are refused. |
| Zip bombs | Member count ≤ 50,000, total ≤ 4 GB, compression ratio ≤ 250, and streamed size may not exceed the declared size (tested). |
| Oversized files | 256 MB per annotation file, checked before JSON parsing (also in folder scans); Streamlit upload limit 500 MB. |
| Malformed annotations | Parsers never crash on bad values: they become NaN plus a reported error. |
| Unexpected encodings | UTF-8 with or without BOM, UTF-16 with BOM, Latin-1 fallback. |
| Spreadsheet formula injection | Text cells starting with `= + - @`, tab or CR get a leading `'` in CSV and XLSX (tested). |
| HTML injection in the UI | Dataset names, labels and file names are HTML-escaped before custom markup. |
| Exposure on the network | Streamlit binds to `localhost`; usage statistics are off. |
| Data leaving the machine | Validation makes no network calls. The only network code is the explicit `labelguard bdd100k fetch`, which reads a pinned public dataset after licence acceptance. |
| Modifying user data | Uploads are copied into a temporary session folder; removing a dataset deletes only that copy. |
| Secrets | None required. CVAT credentials are read from environment variables and never printed or written. `.claude/settings.local.json` and `data/` are git-ignored. |
| Image decompression bombs | Pillow's pixel limit stays on; `DecompressionBombError` (not an `OSError`) is caught so the Inspector falls back to the annotation-only canvas instead of crashing (tested). |
| Temporary files | Every import and upload gets its own fresh folder (never reused, so datasets cannot mix); session folders older than 24 h are removed at start-up. Only `labelguard-session-*` folders are touched (tested). |
| CVAT exports | Extracted with the same safe ZIP extractor; the CVAT stack is bound to `127.0.0.1` by `start-cvat.ps1`. |
| Dependency vulnerabilities | `pip-audit -r requirements.txt` on 23 Nov 2026: no known vulnerabilities. |
| Downloaded data integrity | BDD100K files are verified against the Hub's published SHA-256 / git SHA-1 for a pinned revision before use. |

Report vulnerabilities by opening a private security advisory on the GitHub repository.
