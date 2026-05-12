from abc import ABC, abstractmethod


# §14 — Storage abstraction. Two implementations: LocalStorage and R2Storage.


class Storage(ABC):
    @abstractmethod
    async def put(self, key: str, data: bytes, content_type: str) -> None: ...

    @abstractmethod
    async def get(self, key: str) -> bytes: ...

    @abstractmethod
    async def signed_url(self, key: str, expires_in: int = 3600) -> str: ...

    @abstractmethod
    async def delete(self, key: str) -> None: ...
