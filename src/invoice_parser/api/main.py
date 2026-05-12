import structlog
from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from invoice_parser.api.auth import auth_middleware
from invoice_parser.api.routes import router

logger = structlog.get_logger()

app = FastAPI(title="Invoice Parser", version="0.1.0")

app.middleware("http")(auth_middleware)
app.include_router(router)


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/docs")


@app.get("/health")
async def health():
    return {"status": "ok"}
