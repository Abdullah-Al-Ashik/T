from src.threads_publisher import ThreadsPublisher

class Resp:
    def __init__(self, data, status=200, headers=None): self._data, self.status_code, self.headers = data, status, headers or {}
    def json(self): return self._data

class FakeSession:
    def __init__(self): self.calls=[]
    def request(self, method, url, **kwargs):
        self.calls.append((method,url,kwargs))
        if url.endswith("/threads"): return Resp({"id":"container-1"})
        if url.endswith("/container-1"): return Resp({"id":"container-1","status":"FINISHED"})
        if url.endswith("/threads_publish"): return Resp({"id":"post-1"})
        raise AssertionError(url)

def test_publish_sequence_and_ids():
    session = FakeSession()
    pub = ThreadsPublisher("user-1", "not-a-real-token", session=session, poll_interval=0)
    result = pub.publish_video("https://raw.githubusercontent.com/a/b/main/videos/a.mp4", "caption")
    assert result["container_id"] == "container-1"
    assert result["publication_id"] == "post-1"
    assert [x[0] for x in session.calls] == ["POST", "GET", "POST"]
    assert all("not-a-real-token" not in call[1] and "not-a-real-token" not in str(call[2].get("params", {})) for call in session.calls)


def test_auth_failure_is_permanent_and_safe():
    class BadSession:
        def request(self, method, url, **kwargs):
            return Resp({}, status=401)
    from src.threads_publisher import ThreadsError
    pub = ThreadsPublisher("user-1", "secret-token", session=BadSession())
    try:
        pub.publish_video("https://raw.githubusercontent.com/a/b/main/videos/a.mp4", "caption")
        assert False, "expected auth error"
    except ThreadsError as exc:
        assert exc.category == "authentication_or_permission"
        assert "secret-token" not in str(exc)


def test_ambiguous_publish_timeout_is_flagged():
    from src.threads_publisher import ThreadsError
    class TimeoutSession:
        def request(self, method, url, **kwargs):
            if url.endswith("/threads"):
                return Resp({"id": "container-1"})
            if url.endswith("/container-1"):
                return Resp({"status": "FINISHED"})
            if url.endswith("/threads_publish"):
                raise TimeoutError("must not be surfaced")
            raise AssertionError(url)
    pub = ThreadsPublisher("user-1", "secret-token", session=TimeoutSession(), poll_interval=0)
    try:
        pub.publish_video("https://raw.githubusercontent.com/a/b/main/videos/a.mp4", "caption")
        assert False, "expected ambiguous error"
    except ThreadsError as exc:
        assert exc.ambiguous is True
        assert "secret-token" not in str(exc)


def test_retry_after_is_preserved_and_rate_limit_is_not_ambiguous():
    from src.threads_publisher import ThreadsError
    class LimitedSession:
        def request(self, method, url, **kwargs):
            return Resp({}, status=429, headers={"Retry-After": "42"})
    pub = ThreadsPublisher("user-1", "not-a-real-token", session=LimitedSession())
    try:
        pub.publish_video("https://raw.githubusercontent.com/a/b/main/videos/a.mp4", "caption")
        assert False, "expected rate limit"
    except ThreadsError as exc:
        assert exc.category == "rate_limited"
        assert exc.retry_after_seconds == 42
        assert exc.ambiguous is False
