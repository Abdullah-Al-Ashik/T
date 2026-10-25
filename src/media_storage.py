"""Public GitHub Raw URL construction and unauthenticated URL preflight."""
from urllib.parse import quote
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from src.video_analyzer import public_raw_url


def public_video_url(raw_base_url: str, filename: str) -> str:
    if not filename or filename.startswith(".") or "/" in filename or "\\" in filename or ".." in filename:
        raise ValueError("Unsafe video filename")
    base = raw_base_url.rstrip("/")
    return f"{base}/videos/{quote(filename, safe='')}"


def preflight_url(url: str, session=None, timeout: int = 15) -> bool:
    response = None
    try:
        if session is not None:
            response = session.get(url, headers={"Range": "bytes=0-0"}, allow_redirects=True, timeout=timeout, stream=True)
            status = response.status_code
            content_type = response.headers.get("Content-Type", "").lower()
            return status in (200, 206) and (content_type.startswith("video/") or content_type == "application/octet-stream")
        request = Request(url, headers={"Range": "bytes=0-0", "User-Agent": "ThreadsVideoPublisher/1.0"}, method="GET")
        try:
            response = urlopen(request, timeout=timeout)
            status = response.status
        except HTTPError as exc:
            status = exc.code
            response = exc
        content_type = response.headers.get("Content-Type", "").lower() if response is not None else ""
        return status in (200, 206) and (content_type.startswith("video/") or content_type == "application/octet-stream")
    except (URLError, OSError, TimeoutError):
        return False
    finally:
        if response is not None and hasattr(response, "close"):
            response.close()

__all__ = ["public_raw_url", "public_video_url", "preflight_url"]
