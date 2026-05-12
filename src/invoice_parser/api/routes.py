"""§6 — API routes: POST /jobs, GET /jobs/{id}, GET /jobs/{id}/download."""

import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from invoice_parser.api.schemas import (
    JobGDriveRequest,
    JobLocalPathRequest,
    JobStatusResponse,
)
from invoice_parser.config import settings
from invoice_parser.db.session import AsyncSessionLocal, get_session
from invoice_parser.storage.local import LocalStorage
from invoice_parser.storage.r2 import R2Storage

router = APIRouter()


def _get_storage():
    if settings.storage_backend == "r2":
        return R2Storage(
            account_id=settings.r2_account_id,
            access_key_id=settings.r2_access_key_id,
            secret_access_key=settings.r2_secret_access_key,
            bucket=settings.r2_bucket,
        )
    return LocalStorage(settings.storage_local_path)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(6)}"


async def _create_job_row(
    session: AsyncSession,
    api_key_id: str,
    input_source: str,
    input_manifest: list,
    output_format: str,
    file_count: int | None,
) -> dict:
    job_id = _new_id("job")
    expires_at = None  # set when done
    await session.execute(text("""
        INSERT INTO jobs
          (id, api_key_id, status, input_source, input_manifest,
           output_format, file_count, created_at)
        VALUES
          (:id, :api_key_id, 'queued', :input_source, :input_manifest,
           :output_format, :file_count, now())
    """), {
        "id": job_id,
        "api_key_id": api_key_id,
        "input_source": input_source,
        "input_manifest": json.dumps(input_manifest),
        "output_format": output_format,
        "file_count": file_count,
    })
    await session.commit()
    return {"job_id": job_id, "file_count": file_count}


# ── POST /jobs — file upload ───────────────────────────────────────────────────

@router.post("/jobs")
async def create_job_upload(
    request: Request,
    files: list[UploadFile] = File(...),
    output_format: str = Form("xlsx"),
):
    api_key = request.state.api_key
    storage = _get_storage()

    if len(files) > settings.max_files_per_job:
        raise HTTPException(400, f"Too many files. Max {settings.max_files_per_job}.")

    job_id = _new_id("job")
    manifest = []
    total_bytes = 0

    for f in files:
        data = await f.read()
        total_bytes += len(data)
        if len(data) > settings.max_file_size_mb * 1024 * 1024:
            raise HTTPException(400, f"File {f.filename} exceeds {settings.max_file_size_mb} MB")
        if total_bytes > settings.max_total_upload_mb * 1024 * 1024:
            raise HTTPException(400, f"Total upload exceeds {settings.max_total_upload_mb} MB")

        file_id = secrets.token_hex(8)
        key = f"jobs/{job_id}/inputs/{file_id}.pdf"
        await storage.put(key, data, "application/pdf")
        manifest.append({"file_id": file_id, "filename": f.filename, "storage_key": key})

    estimated_cost = round(len(files) * 0.005, 4)  # rough pre-estimate

    async with AsyncSessionLocal() as session:
        await session.execute(text("""
            INSERT INTO jobs
              (id, api_key_id, status, input_source, input_manifest,
               output_format, file_count, created_at)
            VALUES
              (:id, :api_key_id, 'queued', 'upload', :manifest,
               :output_format, :file_count, now())
        """), {
            "id": job_id,
            "api_key_id": api_key["id"],
            "manifest": json.dumps(manifest),
            "output_format": output_format,
            "file_count": len(files),
        })
        await session.commit()

    return {
        "job_id": job_id,
        "status": "queued",
        "file_count": len(files),
        "estimated_cost_usd": estimated_cost,
        "poll_url": f"/jobs/{job_id}",
        "expires_at": None,
    }


# ── POST /jobs — JSON body (local_path or gdrive) ─────────────────────────────

@router.post("/jobs/source")
async def create_job_source(request: Request, body: JobLocalPathRequest | JobGDriveRequest):
    api_key = request.state.api_key
    job_id = _new_id("job")

    if isinstance(body, JobLocalPathRequest):
        manifest = [{"path": body.path, "recursive": body.recursive}]
        source = "local_path"
    else:
        manifest = [{"folder_id": body.folder_id, "recursive": body.recursive}]
        source = "gdrive"

    async with AsyncSessionLocal() as session:
        await session.execute(text("""
            INSERT INTO jobs
              (id, api_key_id, status, input_source, input_manifest,
               output_format, created_at)
            VALUES
              (:id, :api_key_id, 'queued', :source, :manifest, :output_format, now())
        """), {
            "id": job_id,
            "api_key_id": api_key["id"],
            "source": source,
            "manifest": json.dumps(manifest),
            "output_format": body.output_format,
        })
        await session.commit()

    return {
        "job_id": job_id,
        "status": "queued",
        "file_count": None,
        "estimated_cost_usd": None,
        "poll_url": f"/jobs/{job_id}",
        "expires_at": None,
    }


# ── GET /jobs/{job_id} ────────────────────────────────────────────────────────

@router.get("/jobs/{job_id}")
async def get_job(job_id: str, request: Request):
    api_key = request.state.api_key
    async with AsyncSessionLocal() as session:
        row = (await session.execute(
            text("SELECT * FROM jobs WHERE id = :id AND api_key_id = :kid"),
            {"id": job_id, "kid": api_key["id"]},
        )).mappings().first()

    if not row:
        raise HTTPException(404, "Job not found")

    job = dict(row)
    progress = {
        "files_total": job.get("file_count"),
        "files_completed": job.get("files_completed", 0),
        "files_failed": job.get("files_failed", 0),
        "invoices_extracted": job.get("invoices_extracted", 0),
        "invoices_review": job.get("invoices_review", 0),
    }
    result = None
    if job["status"] == "done":
        downloads = {}
        if job.get("result_xlsx_key"):
            downloads["xlsx"] = f"/jobs/{job_id}/download?format=xlsx"
        if job.get("result_json_key"):
            downloads["json"] = f"/jobs/{job_id}/download?format=json"
        result = {
            "downloads": downloads,
            "summary": {
                "invoices_total": job["invoices_extracted"],
                "invoices_ok": job["invoices_extracted"] - job["invoices_review"],
                "invoices_review": job["invoices_review"],
                "invoices_failed": job["files_failed"],
            },
        }

    return {
        "job_id": job_id,
        "status": job["status"],
        "progress": progress,
        "cost_usd": float(job["cost_usd"]) if job.get("cost_usd") else 0.0,
        "result": result,
        "error": job.get("error"),
    }


# ── GET /jobs/{job_id}/download ───────────────────────────────────────────────

@router.get("/jobs/{job_id}/download")
async def download_job(job_id: str, format: str, request: Request):
    api_key = request.state.api_key
    async with AsyncSessionLocal() as session:
        row = (await session.execute(
            text("SELECT * FROM jobs WHERE id = :id AND api_key_id = :kid"),
            {"id": job_id, "kid": api_key["id"]},
        )).mappings().first()

    if not row:
        raise HTTPException(404, "Job not found")
    job = dict(row)
    if job["status"] != "done":
        raise HTTPException(400, "Job is not done yet")

    storage = _get_storage()
    if format == "xlsx":
        key = job.get("result_xlsx_key")
        content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = f"invoices_{job_id}.xlsx"
    elif format == "json":
        key = job.get("result_json_key")
        content_type = "application/json"
        filename = f"invoices_{job_id}.json"
    else:
        raise HTTPException(400, "format must be xlsx or json")

    if not key:
        raise HTTPException(404, f"No {format} output for this job")

    data = await storage.get(key)
    return StreamingResponse(
        iter([data]),
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── GET /config/gdrive-email ──────────────────────────────────────────────────

@router.get("/config/gdrive-email")
async def gdrive_email():
    import json as _json
    creds = settings.gdrive_service_account_json
    if not creds:
        return {"email": None, "configured": False}
    try:
        info = _json.loads(creds) if creds.strip().startswith("{") else _json.load(open(creds))
        return {"email": info.get("client_email"), "configured": True}
    except Exception:
        return {"email": None, "configured": False}
