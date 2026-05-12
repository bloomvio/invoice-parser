"""§11 — Postgres-backed SKIP LOCKED queue helpers."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


async def claim_next_job(conn: AsyncConnection) -> dict | None:
    """Atomically claim the oldest queued job. Returns row dict or None."""
    result = await conn.execute(text("""
        UPDATE jobs
        SET status = 'running', started_at = now()
        WHERE id = (
            SELECT id FROM jobs
            WHERE status = 'queued'
            ORDER BY created_at
            LIMIT 1
            FOR UPDATE SKIP LOCKED
        )
        RETURNING *
    """))
    row = result.mappings().first()
    return dict(row) if row else None


async def mark_job_done(conn: AsyncConnection, job_id: str, **updates) -> None:
    sets = ", ".join(f"{k} = :{k}" for k in updates)
    await conn.execute(
        text(f"UPDATE jobs SET status = 'done', finished_at = now(), {sets} WHERE id = :id"),
        {"id": job_id, **updates},
    )


async def mark_job_failed(conn: AsyncConnection, job_id: str, error: str) -> None:
    await conn.execute(
        text("UPDATE jobs SET status = 'failed', finished_at = now(), error = :error WHERE id = :id"),
        {"id": job_id, "error": error},
    )


async def increment_progress(
    conn: AsyncConnection,
    job_id: str,
    files_completed: int = 0,
    files_failed: int = 0,
    invoices_extracted: int = 0,
    invoices_review: int = 0,
    cost_usd: float = 0.0,
) -> None:
    await conn.execute(text("""
        UPDATE jobs SET
            files_completed   = files_completed   + :fc,
            files_failed      = files_failed      + :ff,
            invoices_extracted = invoices_extracted + :ie,
            invoices_review   = invoices_review   + :ir,
            cost_usd          = cost_usd          + :cost
        WHERE id = :id
    """), {
        "id": job_id, "fc": files_completed, "ff": files_failed,
        "ie": invoices_extracted, "ir": invoices_review, "cost": cost_usd,
    })
