from __future__ import annotations
import hashlib, subprocess, tempfile, os
from pathlib import Path
from urllib.parse import quote

SUPPORTED = {".mp4", ".mov"}


def discover_videos(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    return sorted((p for p in directory.iterdir() if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in SUPPORTED and not p.name.endswith((".tmp", ".part")) and p.stat().st_size >= 1024), key=lambda p: p.name.casefold())


def stable_video_id(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def validate_video(path: Path, max_bytes: int = 100 * 1024 * 1024) -> None:
    if path.suffix.lower() not in SUPPORTED:
        raise ValueError("Unsupported video extension; use MP4 or MOV")
    if not path.is_file() or path.name.startswith("."):
        raise ValueError("Not an eligible video file")
    size = path.stat().st_size
    if size < 2 or size > max_bytes:
        raise ValueError("Video file is empty or exceeds the configured maximum size")


def extract_frames(path: Path, max_frames: int = 4, sample_window_seconds: int = 5) -> tuple[list[Path], list[float]]:
    """Extract representative JPEG frames; requires ffmpeg installed on PATH."""
    if max_frames < 1 or sample_window_seconds < 1:
        raise ValueError("Frame sampling settings must be positive")
    try:
        tempdir = Path(tempfile.mkdtemp(prefix="threads-frames-"))
    except (OSError, FileNotFoundError) as exc:
        raise RuntimeError(f"Failed to create temporary directory for frame extraction: {exc}") from exc
    timestamps = [round(i * sample_window_seconds / max(max_frames - 1, 1), 2) for i in range(max_frames)] if max_frames > 1 else [0.0]
    frames = []
    for idx, ts in enumerate(timestamps):
        out = tempdir / f"frame-{idx:02d}.jpg"
        cmd = ["ffmpeg", "-nostdin", "-v", "error", "-ss", str(ts), "-i", str(path), "-frames:v", "1", "-vf", "scale='min(768,iw)':-2", "-y", str(out)]
        # Video files are untrusted. ffmpeg receives no API/SMTP/GitHub credentials.
        safe_env = {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"), "HOME": str(tempdir), "LANG": "C.UTF-8"}
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=30, check=False, text=True, env=safe_env, stdin=subprocess.DEVNULL)
        except FileNotFoundError as exc:
            raise FileNotFoundError(f"ffmpeg command not found on PATH; ensure ffmpeg is installed") from exc
        if result.returncode == 0 and out.exists() and out.stat().st_size:
            frames.append(out)
    if not frames:
        raise ValueError("Could not extract any frames; confirm ffmpeg and video validity")
    return frames, timestamps[:len(frames)]


def public_raw_url(owner: str, repo: str, branch: str, filename: str) -> str:
    # Video filenames must be a basename so path traversal cannot escape videos/.
    if not owner or not repo or not branch or not filename or "/" in filename or "\\" in filename or ".." in filename:
        raise ValueError("Invalid public repository URL components")
    return f"https://raw.githubusercontent.com/{quote(owner, safe='')}/{quote(repo, safe='')}/{quote(branch, safe='/')}/videos/{quote(filename, safe='')}"
