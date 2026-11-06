"""Resume URL resolution: join Harly file records to S3 objects.

Harly's API exposes file records (name/size) but no download URL, while its
R2 bucket key embeds an internal storage ID the API never returns. The join
bridges them: list the workspace prefix, match on (filename, size), and hand
the agent the public URL — the agent fetches and reads the file itself.
"""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import unquote

logger = logging.getLogger(__name__)


def pick_resume_file(files: list[dict]) -> dict | None:
    """Prefer a resume*/cv* filename match, else the most recent file."""
    if not files:
        return None
    for entry in files:
        name = str(entry.get("fileName", "")).lower()
        if "resume" in name or name.startswith("cv"):
            return entry
    return sorted(files, key=lambda e: str(e.get("createdAt", "")), reverse=True)[0]


def build_s3_client(endpoint: str, region: str, access_key_id: str, secret_access_key: str):
    """Build a sync boto3 client (no I/O; calls run in threads)."""
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=region or "auto",
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
    )


def _match_keys(s3_client, *, bucket: str, prefix: str, file_name: str, file_size: int) -> list[dict]:
    paginator = s3_client.get_paginator("list_objects_v2")
    matches = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            base = obj["Key"].rsplit("/", 1)[-1]
            names = {base, unquote(base), unquote(file_name)}
            try:
                same_size = int(obj.get("Size", -1)) == int(file_size)
            except (TypeError, ValueError):
                same_size = False
            if file_name in names and same_size:
                matches.append(obj)
    return matches


async def find_resume_key(
    s3_client, *, bucket: str, prefix: str, file_name: str, file_size: int
) -> str | None:
    """Join a Harly file record to its S3 key. Latest LastModified wins ties."""
    matches = await asyncio.to_thread(
        _match_keys, s3_client, bucket=bucket, prefix=prefix, file_name=file_name, file_size=file_size
    )
    if not matches:
        return None
    if len(matches) > 1:
        logger.warning("s3 join multi-match (%d) for %s; picking latest", len(matches), file_name)
    matches.sort(key=lambda o: str(o.get("LastModified") or ""), reverse=True)
    return matches[0]["Key"]
