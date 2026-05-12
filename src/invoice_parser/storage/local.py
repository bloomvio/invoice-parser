from pathlib import Path

from invoice_parser.storage.base import Storage


class LocalStorage(Storage):
    def __init__(self, base_path: str) -> None:
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        dest = self.base_path / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)

    async def get(self, key: str) -> bytes:
        return (self.base_path / key).read_bytes()

    async def signed_url(self, key: str, expires_in: int = 3600) -> str:
        # Served by FastAPI's download endpoint rather than a real signed URL.
        return f"/storage/{key}"

    async def delete(self, key: str) -> None:
        path = self.base_path / key
        if path.exists():
            path.unlink()
