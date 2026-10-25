from __future__ import annotations
import json, time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl
from urllib.request import Request, urlopen

class ThreadsError(RuntimeError):
    def __init__(self, category: str, message: str, transient: bool = False, ambiguous: bool = False, retry_after_seconds: int | None = None):
        super().__init__(message)
        self.category, self.transient, self.ambiguous = category, transient, ambiguous
        self.retry_after_seconds = retry_after_seconds

class ThreadsPublisher:
    def __init__(self, user_id: str, access_token: str, base_url: str = "https://graph.threads.net", timeout: int = 30, session=None, poll_interval: int = 8):
        if not user_id or not access_token:
            raise ValueError("Threads credentials are missing")
        self.user_id, self.token, self.base = user_id, access_token, base_url.rstrip("/")
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.session = session  # Optional test adapter; production uses Python stdlib HTTP only.

    @staticmethod
    def _url_with_params(url: str, params: dict | None) -> str:
        if not params:
            return url
        parts = urlsplit(url)
        existing = parse_qsl(parts.query, keep_blank_values=True)
        query = urlencode(existing + list(params.items()))
        return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))

    def _request(self, method: str, url: str, *, params=None):
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        request_url = self._url_with_params(url, params)
        response_headers = {}
        try:
            if self.session is not None:
                response = self.session.request(method, url, params=params, headers=headers, timeout=self.timeout)
                status_code = response.status_code
                response_headers = getattr(response, "headers", {}) or {}
                data = response.json() if 200 <= status_code < 300 else None
            else:
                req = Request(request_url, headers=headers, method=method.upper())
                try:
                    with urlopen(req, timeout=self.timeout) as response:
                        status_code = response.status
                        response_headers = response.headers
                        raw = response.read()
                except HTTPError as response:
                    status_code = response.code
                    response_headers = response.headers
                    raw = b""
                data = json.loads(raw.decode("utf-8")) if 200 <= status_code < 300 else None
        except TimeoutError as exc:
            raise ThreadsError("network_timeout", "Threads API request timed out", transient=True, ambiguous=(method.upper() == "POST" and "threads_publish" in url)) from exc
        except (URLError, OSError) as exc:
            raise ThreadsError("network_error", "Threads API network error", transient=True, ambiguous=(method.upper() == "POST" and "threads_publish" in url)) from exc
        except ValueError as exc:
            raise ThreadsError("invalid_response", "Threads API returned invalid JSON") from exc
        if status_code == 429:
            retry_after = None
            raw_retry_after = response_headers.get("Retry-After") if response_headers else None
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
            raise ThreadsError("rate_limited", "Threads API rate limit reached", transient=True, retry_after_seconds=retry_after)
        if status_code in (401, 403):
            raise ThreadsError("authentication_or_permission", f"Threads API returned HTTP {status_code}")
        if status_code >= 500:
            raise ThreadsError("server_error", f"Threads API returned HTTP {status_code}", transient=True, ambiguous=(method.upper() == "POST" and "threads_publish" in url))
        if not (200 <= status_code < 300):
            raise ThreadsError("request_rejected", f"Threads API rejected request with HTTP {status_code}")
        if not isinstance(data, dict):
            raise ThreadsError("invalid_response", "Threads API returned an unexpected response structure")
        return data

    def publish_video(self, video_url: str, caption: str, poll_seconds: int | None = None, processing_timeout: int = 360) -> dict:
        poll_seconds = self.poll_interval if poll_seconds is None else poll_seconds
        params = {"media_type": "VIDEO", "video_url": video_url}
        if caption:
            params["text"] = caption
        created = self._request("POST", f"{self.base}/{self.user_id}/threads", params=params)
        container_id = created.get("id")
        if not container_id:
            raise ThreadsError("invalid_response", "Threads container response did not include an ID")
        deadline = time.monotonic() + processing_timeout
        while time.monotonic() < deadline:
            status = self._request("GET", f"{self.base}/{container_id}", params={"fields": "status,error_message"})
            code = str(status.get("status", "")).upper()
            if code in {"FINISHED", "PUBLISHED"}:
                break
            if code in {"ERROR", "EXPIRED"}:
                raise ThreadsError("media_processing_failed", "Threads could not process the video container")
            time.sleep(poll_seconds)
        else:
            raise ThreadsError("processing_timeout", "Threads media processing did not finish before timeout", transient=True)
        try:
            result = self._request("POST", f"{self.base}/{self.user_id}/threads_publish", params={"creation_id": container_id})
        except ThreadsError as exc:
            if exc.transient and exc.category in {"network_timeout", "network_error", "server_error"}:
                exc.ambiguous = True
            raise
        publication_id = result.get("id")
        if not publication_id:
            raise ThreadsError("publication_unconfirmed", "Publish response did not include a publication ID", ambiguous=True)
        return {"container_id": container_id, "publication_id": publication_id}
