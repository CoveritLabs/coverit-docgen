"""Generic, provider-agnostic HTTP transport helpers.

Nothing in this module knows about Jira, CoverIt's internal API shape, or any
other specific service. It's pure transport plumbing that any provider or
client can reuse.
"""

import asyncio
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import json
import mimetypes


async def raw_request(method: str, url: str, body: bytes | None, headers: dict[str, str], timeout: int = 60) -> tuple[int, bytes, dict]:
    return await asyncio.to_thread(_raw_request_sync, method, url, body, headers, timeout)


def _raw_request_sync(method: str, url: str, body: bytes | None, headers: dict[str, str], timeout: int) -> tuple[int, bytes, dict]:
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.status, response.read(), dict(response.headers.items())
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed with {exc.code}: {detail}") from exc


async def json_request(method: str, url: str, payload: dict | None, headers: dict[str, str], timeout: int = 60) -> tuple[int, dict]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req_headers = dict(headers)
    if payload is not None:
        req_headers.setdefault("Content-Type", "application/json")
    status, content, _headers = await raw_request(method, url, body, req_headers, timeout)
    if status == 204 or not content:
        return status, {}
    return status, json.loads(content.decode("utf-8"))


def multipart_file(boundary: str, field_name: str, filename: str, content: bytes, content_type: str | None) -> bytes:
    clean_name = filename.replace('"', "")
    guessed_type = content_type or mimetypes.guess_type(clean_name)[0] or "application/octet-stream"
    return b"".join(
        [
            f"--{boundary}\r\n".encode("utf-8"),
            f'Content-Disposition: form-data; name="{field_name}"; filename="{clean_name}"\r\n'.encode("utf-8"),
            f"Content-Type: {guessed_type}\r\n\r\n".encode("utf-8"),
            content,
            b"\r\n",
            f"--{boundary}--\r\n".encode("utf-8"),
        ]
    )
