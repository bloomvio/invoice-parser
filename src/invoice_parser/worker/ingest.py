"""§10.1 — Source adapters: local filesystem and Google Drive."""

import io
import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass

from invoice_parser.config import settings


@dataclass
class FileRef:
    file_id: str      # stable ID for storage key
    filename: str
    source: str       # "local_path" | "gdrive"
    _meta: dict = None  # source-specific metadata


class IngestSource(ABC):
    @abstractmethod
    async def list_pdfs(self) -> list[FileRef]: ...

    @abstractmethod
    async def fetch(self, file_ref: FileRef) -> bytes: ...


class LocalPathSource(IngestSource):
    def __init__(self, path: str, recursive: bool = True) -> None:
        self.path = path
        self.recursive = recursive

    async def list_pdfs(self) -> list[FileRef]:
        refs = []
        if self.recursive:
            for root, _, files in os.walk(self.path):
                for f in files:
                    if f.lower().endswith(".pdf"):
                        full_path = os.path.join(root, f)
                        refs.append(FileRef(
                            file_id=full_path.replace(os.sep, "_").lstrip("_"),
                            filename=f,
                            source="local_path",
                            _meta={"path": full_path},
                        ))
        else:
            for f in os.listdir(self.path):
                if f.lower().endswith(".pdf"):
                    refs.append(FileRef(
                        file_id=f,
                        filename=f,
                        source="local_path",
                        _meta={"path": os.path.join(self.path, f)},
                    ))
        return refs

    async def fetch(self, file_ref: FileRef) -> bytes:
        with open(file_ref._meta["path"], "rb") as fh:
            return fh.read()


class GoogleDriveSource(IngestSource):
    def __init__(self, folder_id: str, recursive: bool = True) -> None:
        self.folder_id = folder_id
        self.recursive = recursive
        self._service = None

    def _get_service(self):
        if self._service:
            return self._service
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        creds_json = settings.gdrive_service_account_json
        if not creds_json:
            raise RuntimeError("GDRIVE_SERVICE_ACCOUNT_JSON is not configured")

        # Accept either a JSON string or a file path
        if creds_json.strip().startswith("{"):
            info = json.loads(creds_json)
        else:
            with open(creds_json) as fh:
                info = json.load(fh)

        credentials = service_account.Credentials.from_service_account_info(
            info,
            scopes=["https://www.googleapis.com/auth/drive.readonly"],
        )
        self._service = build("drive", "v3", credentials=credentials, cache_discovery=False)
        return self._service

    def _list_folder(self, folder_id: str) -> list[dict]:
        service = self._get_service()
        query = f"'{folder_id}' in parents and trashed=false"
        results = []
        page_token = None
        while True:
            resp = service.files().list(
                q=query,
                fields="nextPageToken,files(id,name,mimeType)",
                pageToken=page_token,
            ).execute()
            for f in resp.get("files", []):
                if f["mimeType"] == "application/pdf":
                    results.append(f)
                elif self.recursive and f["mimeType"] == "application/vnd.google-apps.folder":
                    results.extend(self._list_folder(f["id"]))
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return results

    async def list_pdfs(self) -> list[FileRef]:
        import asyncio
        files = await asyncio.to_thread(self._list_folder, self.folder_id)
        return [
            FileRef(
                file_id=f["id"],
                filename=f["name"],
                source="gdrive",
                _meta={"drive_id": f["id"]},
            )
            for f in files
        ]

    async def fetch(self, file_ref: FileRef) -> bytes:
        import asyncio

        def _download():
            from googleapiclient.http import MediaIoBaseDownload
            service = self._get_service()
            request = service.files().get_media(fileId=file_ref._meta["drive_id"])
            buf = io.BytesIO()
            downloader = MediaIoBaseDownload(buf, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            return buf.getvalue()

        return await asyncio.to_thread(_download)
