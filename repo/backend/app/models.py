from typing import Optional

from pydantic import BaseModel


class RunStatusResponse(BaseModel):
    id: str
    status: str
    stage: str
    shortlist_k: int
    total_candidates: int
    sliced_candidates: int
    best_candidate_id: Optional[str] = None
    error: Optional[str] = None


class ChooseRequest(BaseModel):
    cand_id: str
