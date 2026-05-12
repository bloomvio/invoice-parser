from typing import Any, Literal, Optional
from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str


# ── Job creation ──────────────────────────────────────────────────────────────

class JobCreateUploadResponse(BaseModel):
    job_id: str
    status: str
    file_count: Optional[int]
    estimated_cost_usd: Optional[float]
    poll_url: str
    expires_at: Optional[str]


class JobLocalPathRequest(BaseModel):
    source: Literal["local_path"]
    path: str
    recursive: bool = True
    output_format: Literal["xlsx", "json", "both"] = "xlsx"


class JobGDriveRequest(BaseModel):
    source: Literal["gdrive"]
    folder_id: str
    recursive: bool = True
    output_format: Literal["xlsx", "json", "both"] = "xlsx"


# ── Job status ────────────────────────────────────────────────────────────────

class JobProgress(BaseModel):
    files_total: Optional[int]
    files_completed: int
    files_failed: int
    invoices_extracted: int
    invoices_review: int


class JobResultLinks(BaseModel):
    downloads: dict[str, str]
    summary: dict[str, Any]


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    progress: JobProgress
    cost_usd: Optional[float]
    result: Optional[JobResultLinks]
