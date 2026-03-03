from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import candidates, downloads, events, runs
from .db import init_db
from .jobs.runner import ensure_worker, resume_incomplete_runs

app = FastAPI(title="STL Optimizer")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def on_startup() -> None:
    init_db()
    await ensure_worker()
    await resume_incomplete_runs()


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


app.include_router(runs.router)
app.include_router(candidates.router)
app.include_router(downloads.router)
app.include_router(events.router)

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIR), name="frontend-assets")


@app.get("/")
def frontend_index():
    index_path = FRONTEND_DIR / "index.html"
    return FileResponse(index_path)


@app.get("/{file_name}")
def frontend_file(file_name: str):
    if file_name.startswith("api"):
        raise HTTPException(status_code=404, detail="Not Found")
    file_path = FRONTEND_DIR / file_name
    if file_path.exists() and file_path.is_file():
        return FileResponse(file_path)
    return FileResponse(FRONTEND_DIR / "index.html")
