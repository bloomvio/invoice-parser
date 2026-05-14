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
    asyncio.create_task(worker_loop())
    logger.info("worker_loop_started_in_process")


@app.get("/", include_in_schema=False)
async def root():
    return HTMLResponse(UI_HTML)


@app.get("/health")
async def health():
    return {"status": "ok"}
