"""List and download only the selected public video; never checkout the full media library."""
from __future__ import annotations
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from src.video_analyzer import SUPPORTED, public_raw_url

MAX_VIDEO_BYTES = 100 * 1024 * 1024


def discover_public_video_names(owner: str, repo: str, branch: str, timeout: int = 20) -> list[str]:
    if not all((owner, repo, branch)):
        raise ValueError("Public repository owner, name and branch are required")
    url = f"https://api.github.com/repos/{quote(owner, safe='')}/{quote(repo, safe='')}/contents/videos?ref={quote(branch, safe='')}"
    req = Request(url, headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "ThreadsVideoPublisher/1.0"})
    try:
        with urlopen(req, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code == 404:
            return []
        if exc.code == 403:
            raise RuntimeError("GitHub public Contents API rate limit or access error (HTTP 403)") from exc
        raise RuntimeError(f"GitHub public Contents API request failed (HTTP {exc.code})") from exc
    except (URLError, OSError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RuntimeError("GitHub public Contents API request failed safely") from exc
    if not isinstance(data, list):
        raise RuntimeError("GitHub Contents API returned an unexpected response structure")
    names = []
    for item in data:
        if not isinstance(item, dict) or item.get("type") != "file":
            continue
        name = item.get("name")
        size = item.get("size", 0)
        if not isinstance(name, str) or not name or name.startswith(".") or "/" in name or "\\" in name or ".." in name or name.endswith((".tmp", ".part")):
            continue
        if Path(name).suffix.lower() not in SUPPORTED or not isinstance(size, int) or size <= 0 or size > MAX_VIDEO_BYTES:
            continue
        names.append(name)
    return sorted(set(names), key=str.casefold)


def download_public_video(owner: str, repo: str, branch: str, filename: str, destination: Path, timeout: int = 45) -> Path:
    url = public_raw_url(owner, repo, branch, filename)
    req = Request(url, headers={"Accept": "video/mp4,video/quicktime,application/octet-stream;q=0.8", "User-Agent": "ThreadsVideoPublisher/1.0"})
    destination.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    try:
        with urlopen(req, timeout=timeout) as response, destination.open("wb") as out:
            content_type = response.headers.get("Content-Type", "").lower()
            if not (content_type.startswith("video/") or content_type == "application/octet-stream"):
                raise RuntimeError("Public video URL returned an unexpected content type")
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_VIDEO_BYTES:
                    raise RuntimeError("Video exceeds the configured maximum download size")
                out.write(chunk)
    except HTTPError as exc:
        try: destination.unlink(missing_ok=True)
        except OSError: pass
        raise RuntimeError(f"Public video download failed (HTTP {exc.code})") from exc
    except RuntimeError:
        try: destination.unlink(missing_ok=True)
        except OSError: pass
        raise
    except (URLError, OSError, TimeoutError) as exc:
        try: destination.unlink(missing_ok=True)
        except OSError: pass
        raise RuntimeError("Public video download failed safely") from exc
    if total <= 1:
        destination.unlink(missing_ok=True)
        raise RuntimeError("Downloaded video is empty or invalid")
    return destination
