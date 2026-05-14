import asyncio

import structlog
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from invoice_parser.api.auth import auth_middleware
from invoice_parser.api.routes import router
from invoice_parser.api.ui import UI_HTML

logger = structlog.get_logger()

app = FastAPI(title="Invoice Parser", version="0.1.0", docs_url=None, redoc_url=None)

app.middleware("http")(auth_middleware)
app.include_router(router)


@app.on_event("startup")
async def start_worker():
    from invoice_parser.worker.main import worker_loop

    async def _supervised():
        while True:
            try:
                await worker_loop()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("worker_loop_crashed_restarting", error=str(exc))
                await asyncio.sleep(5)

    asyncio.create_task(_supervised())
    logger.info("worker_loop_started_in_process")


@app.get("/", include_in_schema=False)
async def root():
    return HTMLResponse(UI_HTML)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/debug/status", include_in_schema=False)
async def debug_status():
    import os
    from invoice_parser.config import settings
    from invoice_parser.worker import main as worker_main

    storage_path = settings.storage_local_path
    try:
        tree = []
        for root, dirs, files in os.walk(storage_path):
            for f in files:
                full = os.path.join(root, f)
                tree.append({"path": full, "size": os.path.getsize(full)})
    except Exception as e:
        tree = [{"error": str(e)}]

    return {
        "worker_semaphore_active": worker_main._semaphore is not None,
        "storage_local_path": storage_path,
        "storage_files": tree[:50],
    }
