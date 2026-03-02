from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class RunCreate(BaseModel):
    input_path: str
    output_path: str
    profile: str = "Creality_220_Generic"
    top_k: int = 5
    slice_top_n: int = 12
    weight_preset: str = "Hybrid"
    overhang_angle: int = 45
    dry_run: bool = False


class RunSummary(BaseModel):
    id: str
    created_at: str
    started_at: Optional[str]
    finished_at: Optional[str]
    status: str
    input_path: str
    output_path: str
    profile: str
    last_heartbeat: Optional[str]
    engine_mode: str


class ModelResult(BaseModel):
    id: str
    run_id: str
    model_path: str
    status: str
    best_score: Optional[float]
    metrics_json: dict = Field(default_factory=dict)
    artifacts_json: dict = Field(default_factory=dict)


class RunDetail(RunSummary):
    params_json: dict = Field(default_factory=dict)
    models: list[ModelResult] = Field(default_factory=list)


RunStatus = Literal["PENDING", "RUNNING", "PAUSED", "COMPLETED", "FAILED", "STOPPED", "INTERRUPTED"]
