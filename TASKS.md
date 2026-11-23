# LabelGuard: progress checklist

`[x]` done and verified · `[~]` partial (see note) · `[ ]` not done

## Phase 1: environment and skills
- [x] Windows 11 Pro, 31.7 GB RAM, Python 3.12 venv; Git identity verified (unchanged)
- [x] Attribution disabled in `.claude/settings.local.json` (git-ignored); commits carry no co-author trailer
- [~] Official `frontend-design` plugin: install card offered in the desktop app (no `claude` CLI on PATH);
      its SKILL.md was read from anthropics/claude-plugins-official and applied (docs/DESIGN_SYSTEM.md)
- [x] Project skills: labelguard-design-system, annotation-inspector-ux, visual-qa
- [x] Browser tooling: Claude browser pane + Playwright driving installed Microsoft Edge (no browser download)

## Phase 2: design
- [x] Design plan and review 1 (docs/DESIGN_SYSTEM.md)

## Phase 3: core backend
- [x] Normalized model; CVAT images and video XML; COCO; BDD100K / Scalabel (inclusive box2d)
- [x] Safe ZIP import (traversal, symlinks, bombs); defusedxml
- [x] Rule registry: 33 rules (integrity, boxes, polygons, keypoints, tracks) and 6 profiles

## Phase 4: frontend
- [x] Shell, Overview, Datasets, Issues, Inspector, Reports, Settings; dark and light themes
- [x] Keyboard navigation in Inspector (← → findings, Shift+← → images, Esc), verified in browser

## Real-world data (BDD100K)
- [x] Environment inspection: no Docker, WSL2 without distro, 17.4 GB free, no existing CVAT, ports free
- [x] Official host dl.cv.ethz.ch unresolvable; bdd-data.berkeley.edu expired TLS → license-permitted HF
      redistribution `dronefreak/BDD100K`, pinned revision, per-file checksum verification (user-approved approach)
- [x] Smoke (20) and standard (100) subsets of real val images and original labels; provenance manifests
- [x] Native BDD100K adapter + COCO and CVAT XML conversion, verified lossless on 1,643 real boxes
- [x] Deterministic corruption copy (9 error types × 3) and manifest; evaluation 27/27, 0 FP
- [ ] Extended subset (500): available, not run (user asked to stay at 20–100 images)
- [ ] Video-track anomaly on real BDD100K MOT data: not done (no MOT data downloaded)

## CVAT
- [x] Automation prepared: start-cvat.ps1, stop-cvat.ps1, cvat_bdd100k_e2e.py, test-bdd100k.ps1
- [ ] CVAT installed and round trip executed: blocked until Docker Desktop is installed and disk space freed

## Testing and QA
- [x] 95 tests pass locally (91 level 1 incl. headless Streamlit pages + 4 real-data); Ruff clean
- [x] Visual QA: 60 captures (2 themes × 5 viewports × 6 pages), 0 overflow, 0 exceptions
- [x] Windows launcher verified (existing env and fresh first-run in a path with spaces)

## Docs and publication
- [x] README, ARCHITECTURE, VALIDATION_RULES (generated), BDD100K_INTEGRATION, REAL_WORLD_EVALUATION,
      DESIGN_SYSTEM, DEMO_SCRIPT, SECURITY
- [ ] GitHub repository created and pushed; CI green

## Visual QA log
See docs/DESIGN_SYSTEM.md, reviews 2 and 3: mojibake names, wrapped navigation, 20× zoom blur,
edge-clamped tags, coordinate overflow, fractional ticks, silent import failure, lost session on
refresh, network binding, mobile sidebar overlay, mobile canvas order, split definition lists,
pluralisation, empty table row. All were fixed and re-captured.
