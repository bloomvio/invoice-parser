"""§13 — Create an API key and insert it into the database.

Usage:
    python scripts/create_api_key.py "key name"

Prints the raw key once. It is never stored in plaintext.
"""

import asyncio
import os
import secrets
import sys
from datetime import datetime, timezone
from hashlib import sha256

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dotenv import load_dotenv

load_dotenv()


async def create_key(name: str) -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        print("ERROR: DATABASE_URL is not set. Copy .env.example to .env and fill it in.")
        sys.exit(1)

    raw_key = "aug_" + secrets.token_urlsafe(24)
    hashed = sha256(raw_key.encode()).hexdigest()
    key_id = "key_" + secrets.token_hex(6)

    engine = create_async_engine(database_url)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO api_keys (id, hashed_key, name, created_at)"
                " VALUES (:id, :hashed_key, :name, :created_at)"
            ),
            {
                "id": key_id,
                "hashed_key": hashed,
                "name": name,
                "created_at": datetime.now(timezone.utc),
            },
        )
    await engine.dispose()

    print(f"Created key {key_id} ('{name}').")
    print(f"Raw key (save this — won't be shown again): {raw_key}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python scripts/create_api_key.py "key name"')
        sys.exit(1)

    asyncio.run(create_key(sys.argv[1]))
