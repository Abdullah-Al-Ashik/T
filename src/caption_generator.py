from __future__ import annotations
import base64, json, re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

class GeminiError(RuntimeError):
    def __init__(self, category: str, message: str, transient: bool = False, retry_after_seconds: int | None = None):
        super().__init__(message)
        self.category = category
        self.transient = transient
        self.retry_after_seconds = retry_after_seconds


SYSTEM_PROMPT = """You write concise, accurate Threads video captions. Analyze only the supplied representative video frames. Do not infer unsupported facts. Return valid JSON only with exactly these keys: caption (string) and hashtags (array of strings). Make the caption natural, engaging and curiosity-driven without deceptive clickbait. Hashtags must be relevant to visible content, at most five, no duplicates, and each should start with #. Avoid filler and unnecessary emoji."""


def _parse_json(text: str) -> dict:
    candidate = text.strip().replace("\\n", "\n")
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate, flags=re.I)
        candidate = re.sub(r"\s*```$", "", candidate)
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ValueError("Gemini returned malformed caption JSON") from exc
    if not isinstance(data, dict) or not isinstance(data.get("caption"), str) or not isinstance(data.get("hashtags"), list):
        raise ValueError("Gemini caption response has an invalid schema")
    tags = []
    for item in data["hashtags"]:
        if isinstance(item, str):
            tag = item.strip()
            if tag and not tag.startswith("#"):
                tag = "#" + tag
            if tag and not re.search(r"\s", tag) and re.fullmatch(r"#[\w]+", tag, flags=re.UNICODE) and tag.lower() not in {x.lower() for x in tags}:
                tags.append(tag)
    caption = " ".join(data["caption"].split())
    return {"caption": caption, "hashtags": tags[:5]}


def build_caption_text(data: dict, max_chars: int = 500, max_hashtags: int = 5) -> str:
    caption = data["caption"].strip()
    tags = data.get("hashtags", [])[:max_hashtags]
    text = " ".join(part for part in (caption, " ".join(tags)) if part).strip()
    if len(text) <= max_chars:
        return text
    suffix = " " + " ".join(tags) if tags else ""
    room = max_chars - len(suffix)
    if room <= 0:
        return " ".join(tags)[:max_chars]
    caption = caption[:room].rsplit(" ", 1)[0].rstrip(" ,.;:-")
    return (caption + suffix)[:max_chars].strip()


def generate_caption(frame_paths: list[Path], api_key: str, model: str, endpoint: str, max_chars: int = 500, max_hashtags: int = 5) -> str:
    if not api_key:
        raise ValueError("AI_API_KEY is not configured")
    content = [{"type": "text", "text": "Analyze these video frames in chronological order and create a specific English Threads caption. Return JSON only."}]
    for path in frame_paths:
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}})
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": content}],
        "response_format": {"type": "json_object"},
    }
    request = Request(endpoint, data=json.dumps(payload).encode("utf-8"), headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "Accept": "application/json"}, method="POST")
    response_headers = {}
    try:
        with urlopen(request, timeout=60) as response:
            status_code = response.status
            response_headers = response.headers
            raw_body = response.read()
    except HTTPError as exc:
        status_code = exc.code
        response_headers = exc.headers or {}
        raw_body = b""
    except (URLError, OSError, TimeoutError) as exc:
        raise GeminiError("network_error", "Gemini API network request failed", transient=True) from exc
    if status_code >= 400:
        # Do not include response body or request headers; providers may echo sensitive data.
        category = "rate_limit" if status_code == 429 else ("authentication" if status_code in (401, 403) else ("server_error" if status_code >= 500 else "request_error"))
        retry_after = None
        try:
            raw_retry_after = response_headers.get("Retry-After")
        except Exception:
            raw_retry_after = None
        if raw_retry_after:
            try:
                retry_after = max(0, int(raw_retry_after))
            except (ValueError, TypeError):
                try:
                    retry_date = parsedate_to_datetime(raw_retry_after)
                    if retry_date.tzinfo is None:
                        retry_date = retry_date.replace(tzinfo=timezone.utc)
                    retry_after = max(0, int((retry_date - datetime.now(timezone.utc)).total_seconds()))
                except (TypeError, ValueError, OverflowError):
                    retry_after = None
        raise GeminiError(category, f"Gemini API {category} error (HTTP {status_code})", transient=(status_code == 429 or status_code >= 500), retry_after_seconds=retry_after)
    try:
        result = json.loads(raw_body.decode("utf-8"))
        raw = result["choices"][0]["message"].get("content") or ""
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
        raise ValueError("Gemini API returned an unexpected response structure") from exc
    data = _parse_json(raw)
    return build_caption_text(data, max_chars=max_chars, max_hashtags=max_hashtags)


def compose_caption(data: dict, max_chars: int = 500, max_hashtags: int = 5) -> str:
    return build_caption_text(data, max_chars=max_chars, max_hashtags=max_hashtags)
