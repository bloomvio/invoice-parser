import boto3

from invoice_parser.storage.base import Storage


# §14 — Cloudflare R2 implementation (v2). boto3 calls are synchronous;
# wrap with asyncio.to_thread if hot-path performance becomes a concern.


class R2Storage(Storage):
    def __init__(
        self,
        account_id: str,
        access_key_id: str,
        secret_access_key: str,
        bucket: str,
    ) -> None:
        self.bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
        )

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self._client.put_object(
            Bucket=self.bucket, Key=key, Body=data, ContentType=content_type
        )

    async def get(self, key: str) -> bytes:
        response = self._client.get_object(Bucket=self.bucket, Key=key)
        return response["Body"].read()

    async def signed_url(self, key: str, expires_in: int = 3600) -> str:
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_in,
        )

    async def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self.bucket, Key=key)
