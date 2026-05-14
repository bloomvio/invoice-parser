"""§11 — Worker entrypoint: poll loop + per-job processing."""

import asyncio
import json
import secrets
from datetime import datetime, timedelta, timezone

import structlog

from invoice_parser.config import settings
from invoice_parser.db.queue import (
    claim_next_job,
    increment_progress,
    mark_job_done,
    mark_job_failed,
)
from invoice_parser.db.session import engine
from invoice_parser.storage.local import LocalStorage
from invoice_parser.storage.r2 import R2Storage
from invoice_parser.worker import render, segment
from invoice_parser.worker.emit import generate_json, generate_xlsx
from invoice_parser.worker.ingest import FileRef, GoogleDriveSource, LocalPathSource
from invoice_parser.worker.pipeline import process_invoice_segment

logger = structlog.get_logger()

_semaphore: asyncio.Semaphore | None = None


def _get_storage():
    if settings.storage_backend == "r2":
        return R2Storage(
            account_id=settings.r2_account_id,
            access_key_id=settings.r2_access_key_id,
            secret_access_key=settings.r2_secret_access_key,
            bucket=settings.r2_bucket,
        )
    return LocalStorage(settings.storage_local_path)


async def _process_file(storage, job_id: str, file_ref: FileRef, source) -> tuple[list, list]:
    """Render, segment, and extract all invoices from one PDF. Returns (results, skipped)."""
    log = logger.bind(job_id=job_id, file=file_ref.filename)

    pdf_bytes = await source.fetch(file_ref)
    storage_key = f"jobs/{job_id}/inputs/{file_ref.file_id}.pdf"
    await storage.put(storage_key, pdf_bytes, "application/pdf")

    # Render all pages
    log.info("rendering_pdf")
    pages = await asyncio.to_thread(render.render_pages, pdf_bytes)
    for p in pages:
        await storage.put(
            f"jobs/{job_id}/renders/{file_ref.file_id}/page_{p.page_number}_hires.png",
            p.hi_res, "image/png",
        )
        await storage.put(
            f"jobs/{job_id}/renders/{file_ref.file_id}/page_{p.page_number}_thumb.png",
            p.lo_res, "image/png",
        )

    # Segment
    log.info("segmenting_pdf", pages=len(pages))
    seg = await segment.segment_pdf([p.lo_res for p in pages])

    # Process each invoice segment
    results = []
    for idx, inv_seg in enumerate(seg.invoices, start=1):
        result = await process_invoice_segment(
            storage=storage,
            job_id=job_id,
            file_id=file_ref.file_id,
            pages=inv_seg.pages,
            invoice_index=idx,
        )
        inv_id = "inv_" + secrets.token_hex(6)
        results.append((inv_id, result))

    return results, seg.skipped_pages


async def _process_job(job: dict) -> None:
    log = logger.bind(job_id=job["id"])
    log.info("job_started")
    storage = _get_storage()

    manifest: list[dict] = job.get("input_manifest", [])
    source_type = job["input_source"]
    all_results = []
    all_skipped = []

    if source_type == "upload":
        # Files already in storage; build FileRefs from manifest
        file_refs = [
            FileRef(file_id=m["file_id"], filename=m["filename"], source="upload")
            for m in manifest
        ]
        source = None  # already in storage; fetch directly
    elif source_type == "local_path":
        path = manifest[0].get("path", "")
        source = LocalPathSource(path, recursive=manifest[0].get("recursive", True))
        file_refs = await source.list_pdfs()
    elif source_type == "gdrive":
        folder_id = manifest[0].get("folder_id", "")
        source = GoogleDriveSource(folder_id, recursive=manifest[0].get("recursive", True))
        file_refs = await source.list_pdfs()
    else:
        raise ValueError(f"Unknown input_source: {source_type}")

    async with engine.begin() as conn:
        from sqlalchemy import text
        await conn.execute(
            text("UPDATE jobs SET file_count = :n WHERE id = :id"),
            {"n": len(file_refs), "id": job["id"]},
        )

    for file_ref in file_refs:
        try:
            if source_type == "upload":
                # For uploads, PDF bytes were already stored; re-use LocalPathSource logic
                # by fetching from storage directly
                class _StorageFetchSource:
                    async def fetch(self, fr: FileRef) -> bytes:
                        return await storage.get(f"jobs/{job['id']}/inputs/{fr.file_id}.pdf")
                results, skipped = await _process_file(storage, job["id"], file_ref, _StorageFetchSource())
            else:
                results, skipped = await _process_file(storage, job["id"], file_ref, source)

            all_results.extend(results)
            all_skipped.extend(skipped)

            review_count = sum(1 for _, r in results if r.invoice.status == "review")
            cost = sum(r.cost_usd for _, r in results)

            async with engine.begin() as conn:
                await increment_progress(
                    conn, job["id"],
                    files_completed=1,
                    invoices_extracted=len(results),
                    invoices_review=review_count,
                    cost_usd=cost,
                )
                # Persist invoice rows
                from sqlalchemy import text
                for inv_id, result in results:
                    inv = result.invoice
                    await conn.execute(text("""
                        INSERT INTO invoices
                          (id, job_id, source_file, source_pages, invoice_index_in_file,
                           status, notes, cost_usd, models_used, extracted, audit, created_at)
                        VALUES
                          (:id, :job_id, :source_file, :source_pages, :invoice_index,
                           :status, :notes, :cost_usd, :models_used, :extracted, :audit, now())
                    """), {
                        "id": inv_id,
                        "job_id": job["id"],
                        "source_file": inv.source_file,
                        "source_pages": inv.source_pages,
                        "invoice_index": inv.invoice_index_in_file,
                        "status": inv.status,
                        "notes": inv.notes,
                        "cost_usd": result.cost_usd,
                        "models_used": result.models_used,
                        "extracted": json.dumps(inv.model_dump(mode="json")),
                        "audit": json.dumps(result.audit),
                    })

        except Exception as exc:
            log.exception("file_processing_failed", file=file_ref.filename, error=str(exc))
            async with engine.begin() as conn:
                await increment_progress(conn, job["id"], files_failed=1)

    # Emit output files
    output_format = job.get("output_format", "xlsx")
    result_xlsx_key = result_json_key = None

    if output_format in ("xlsx", "both"):
        xlsx_bytes = generate_xlsx(job["id"], all_results, all_skipped)
        result_xlsx_key = f"jobs/{job['id']}/output.xlsx"
        await storage.put(result_xlsx_key, xlsx_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    if output_format in ("json", "both"):
        json_bytes = generate_json(job["id"], all_results, all_skipped)
        result_json_key = f"jobs/{job['id']}/output.json"
        await storage.put(result_json_key, json_bytes, "application/json")

    expires_at = datetime.now(timezone.utc) + timedelta(days=30)
    async with engine.begin() as conn:
        await mark_job_done(
            conn, job["id"],
            result_xlsx_key=result_xlsx_key,
            result_json_key=result_json_key,
            expires_at=expires_at,
        )
    log.info("job_done", invoices=len(all_results))


async def worker_loop() -> None:
    global _semaphore
    _semaphore = asyncio.Semaphore(settings.worker_concurrency)
    log = logger.bind(component="worker")
    log.info("worker_loop_starting")

    while True:
        try:
            async with engine.begin() as conn:
                job = await claim_next_job(conn)

            if not job:
                await asyncio.sleep(settings.worker_poll_interval_seconds)
                continue

            try:
                await _process_job(job)
            except Exception as exc:
                log.exception("job_failed_unexpectedly", job_id=job["id"], error=str(exc))
                try:
                    async with engine.begin() as conn:
                        await mark_job_failed(conn, job["id"], str(exc))
                except Exception:
                    log.exception("mark_job_failed_error", job_id=job["id"])

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("worker_poll_error", error=str(exc))
            await asyncio.sleep(5)


async def main() -> None:
    await worker_loop()


if __name__ == "__main__":
    asyncio.run(main())
