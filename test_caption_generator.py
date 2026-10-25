import json
import pytest
from src.caption_generator import _parse_json, compose_caption

def test_parse_fenced_json_and_normalize_hashtags():
    got = _parse_json('```json\\n{"caption":"Look closely","hashtags":["nature"," #WildLife ","bad tag"]}\\n```')
    assert got == {"caption": "Look closely", "hashtags": ["#nature", "#WildLife"]}

def test_invalid_json_raises():
    with pytest.raises(ValueError):
        _parse_json("no json here")

def test_caption_length_limit():
    out = compose_caption({"caption": "A very long caption " * 40, "hashtags": ["#Nature"]}, 100, 1)
    assert len(out) <= 100
    assert "#Nature" in out


def test_gemini_request_uses_fixed_model_endpoint_and_does_not_echo_key(monkeypatch, tmp_path):
    import json
    from src import caption_generator
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"jpeg")
    captured = {}
    class Response:
        status = 200
        headers = {}
        def read(self):
            return json.dumps({"choices": [{"message": {"content": '{"caption":"A real scene","hashtags":["#Nature"]}'}}]}).encode()
        def __enter__(self): return self
        def __exit__(self, *args): pass
    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["payload"] = json.loads(request.data.decode())
        return Response()
    monkeypatch.setattr(caption_generator, "urlopen", fake_urlopen)
    out = caption_generator.generate_caption([frame], "test-secret", "gemini-3.5-flash-lite", "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions")
    assert out == "A real scene #Nature"
    assert captured["url"].endswith("/v1beta/openai/chat/completions")
    assert captured["payload"]["model"] == "gemini-3.5-flash-lite"
    assert "test-secret" not in str(captured["payload"])
    assert "Bearer test-secret" in captured["headers"].get("Authorization", "")


def test_gemini_429_preserves_retry_after_without_exposing_key(monkeypatch, tmp_path):
    from email.message import Message
    from urllib.error import HTTPError
    from src import caption_generator
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"jpeg")
    headers = Message()
    headers["Retry-After"] = "15"
    def fake_urlopen(request, timeout):
        raise HTTPError(request.full_url, 429, "limited", headers, None)
    monkeypatch.setattr(caption_generator, "urlopen", fake_urlopen)
    with pytest.raises(caption_generator.GeminiError) as caught:
        caption_generator.generate_caption([frame], "test-secret", "gemini-3.5-flash-lite", "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions")
    assert caught.value.category == "rate_limit"
    assert caught.value.retry_after_seconds == 15
    assert "test-secret" not in str(caught.value)
