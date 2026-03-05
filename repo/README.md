# Local STL Orientation Optimizer (PrusaSlicer-based)

Linux-first local-only STL orientation optimizer with FastAPI backend + SQLite + vanilla JS/Three.js frontend.

## Features
- Upload STL and run two-stage orientation search.
- Stage 1 fast geometric heuristics with up to 250 orientations.
- Stage 2 PrusaSlicer CLI slicing for shortlisted candidates.
- Ranking weighted toward support reduction and also print time, quality, stability.
- Candidate browser with slicer-like layer preview and path-type toggles.
- Choose candidate and download ZIP bundle (`rotated STL + G-code + report`).
- Resume queued/running jobs on backend restart.

## Install
```bash
cd repo/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Install PrusaSlicer CLI (Linux package or AppImage) and ensure command exists:
```bash
prusa-slicer --help
```

See `scripts/install_prusa.md` for notes.

## Run locally
Recommended (single-origin, easiest):
```bash
cd repo
./scripts/run_dev_backend.sh
```
Open `http://localhost:8000`.

Alternative (separate frontend static host):
```bash
cd repo
./scripts/run_dev_backend.sh
# second terminal
./scripts/run_dev_frontend.sh
```
Open `http://localhost:5173` (frontend auto-targets backend on :8000).

## API
- `POST /api/runs` upload STL
- `GET /api/runs/{run_id}` run status
- `GET /api/runs/{run_id}/candidates`
- `GET /api/runs/{run_id}/candidates/{cand_id}/preview`
- `POST /api/runs/{run_id}/choose`
- `GET /api/runs/{run_id}/download`
- `GET /api/runs/{run_id}/events` (SSE)

## Runtime artifacts
Generated under `repo/data/runs/<run_id>/` with input, shortlist, stage2 files, ranking results, chosen artifacts, and downloadable ZIP.

## Known limitations
- PrusaSlicer profile tuning is minimal in MVP.
- Candidate dedupe and scoring are heuristic and may need calibration per printer/material.
- Preview renderer draws 2D XY toolpaths by layer and is not a full volumetric slicer viewer.
