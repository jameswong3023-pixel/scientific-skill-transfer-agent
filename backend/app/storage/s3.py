import hashlib
import posixpath
import uuid
from dataclasses import dataclass
from typing import BinaryIO

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.config import settings


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_relpath(path: str) -> str:
    """Reject anything that could escape its prefix once joined.

    Agent-generated code names its own output files, so these values are not
    trusted input. A key like `runs/<id>/../../secrets` would otherwise read and
    write outside the run's namespace.
    """
    if path.startswith("/") or path.startswith("\\"):
        raise ValueError(f"absolute path not allowed: {path}")
    normed = posixpath.normpath(path.replace("\\", "/"))
    if normed.startswith("..") or "/../" in f"/{normed}/":
        raise ValueError(f"path traversal not allowed: {path}")
    return normed


def paper_key(paper_id: uuid.UUID, filename: str) -> str:
    return f"papers/{paper_id}/source.pdf"


def paper_page_key(paper_id: uuid.UUID, page_number: int) -> str:
    return f"papers/{paper_id}/pages/{page_number:03d}.png"


def dataset_file_key(dataset_id: uuid.UUID, role: str, filename: str) -> str:
    """Role is part of the key, so ground truth lives under its own prefix and
    can never be reached by a prefix listing of the agent-visible inputs."""
    return f"datasets/{dataset_id}/{role}/{_safe_relpath(filename)}"


def artifact_key(run_id: uuid.UUID, path: str) -> str:
    return f"runs/{run_id}/{_safe_relpath(path)}"


@dataclass(frozen=True)
class PutResult:
    key: str
    sha256: str
    bytes: int


class ObjectStore:
    def __init__(self) -> None:
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
            config=Config(
                signature_version="s3v4",
                retries={"max_attempts": 3},
                # Without explicit timeouts botocore waits 60s per connect
                # attempt. When MinIO is not yet resolvable — a cold `docker
                # compose up`, or a unit test run with no stack at all — that
                # turns a startup bucket check into a multi-minute stall.
                connect_timeout=3,
                read_timeout=15,
            ),
        )
        self.bucket = settings.s3_bucket

    def ensure_bucket(self) -> None:
        try:
            self._client.head_bucket(Bucket=self.bucket)
        except ClientError:
            self._client.create_bucket(Bucket=self.bucket)

    def put_bytes(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> PutResult:
        self._client.put_object(
            Bucket=self.bucket, Key=key, Body=data, ContentType=content_type
        )
        return PutResult(key=key, sha256=sha256_bytes(data), bytes=len(data))

    def put_fileobj(self, key: str, fh: BinaryIO, content_type: str) -> None:
        self._client.upload_fileobj(
            fh, self.bucket, key, ExtraArgs={"ContentType": content_type}
        )

    def get_bytes(self, key: str) -> bytes:
        return self._client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def open_stream(self, key: str):
        return self._client.get_object(Bucket=self.bucket, Key=key)["Body"]

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError:
            return False

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self.bucket, Key=key)

    def list_prefix(self, prefix: str) -> list[str]:
        keys: list[str] = []
        token: str | None = None
        while True:
            kwargs = {"Bucket": self.bucket, "Prefix": prefix}
            if token:
                kwargs["ContinuationToken"] = token
            resp = self._client.list_objects_v2(**kwargs)
            keys.extend(o["Key"] for o in resp.get("Contents", []))
            if not resp.get("IsTruncated"):
                return keys
            token = resp.get("NextContinuationToken")

    def presigned_url(self, key: str, expires: int = 3600) -> str:
        return self._client.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=expires
        )


store = ObjectStore()
