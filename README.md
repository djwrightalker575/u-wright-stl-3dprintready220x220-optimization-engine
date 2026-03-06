# Creality 220 Orientation Optimizer (Local Operator UI)

Brand: **U-Wright Open Innovations**

## Features
- FastAPI + SQLite local-only operator interface
- Background run execution with automatic mock fallback when real CLI is unavailable
- Pause/resume/stop controls
- Persistent run history and restart-safe interrupted-state recovery
- Results ranking, logs, and artifact download endpoints
- Server-rendered HTML views with minimal polling JavaScript

## Install
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Start UI
```bash
orienter ui
```

Server:
- http://localhost:8787

## API
- `POST /api/runs`
- `GET /api/runs`
- `GET /api/runs/{id}`
- `POST /api/runs/{id}/pause`
- `POST /api/runs/{id}/resume`
- `POST /api/runs/{id}/stop`
- `GET /api/runs/{id}/logs?tail=200`
- `GET /api/runs/{id}/download/{artifact}`

## Output Layout
```
<output_root>/runs/<run_id>/
  rotated_stl/
  gcode/
  reports/
  logs/
```

## Notes
- On server restart, any previously RUNNING runs are marked `INTERRUPTED`.
- Cache key uses model content hash + profile hash.
- `/health` is provided for smoke tests.
