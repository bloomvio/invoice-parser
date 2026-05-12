from hashlib import sha256

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from invoice_parser.db.session import AsyncSessionLocal

# These paths skip auth — needed for infra health checks and OpenAPI docs.
EXEMPT_PATHS = {"/", "/health"}


async def auth_middleware(request: Request, call_next):
    if request.url.path in EXEMPT_PATHS:
        return await call_next(request)

    raw_key = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if not raw_key:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)

    hashed = sha256(raw_key.encode()).hexdigest()

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text(
                "SELECT * FROM api_keys"
                " WHERE hashed_key = :hashed AND revoked_at IS NULL"
            ),
            {"hashed": hashed},
        )
        api_key = result.mappings().first()

    if not api_key:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)

    request.state.api_key = dict(api_key)
    return await call_next(request)
