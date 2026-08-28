from __future__ import annotations

import json

import httpx
import pytest

from planqa_review.llm.gateway import GatewayClient


def _client_with_transport(handler) -> GatewayClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(base_url="https://fake.gateway/v1/gateway", transport=transport)
    return GatewayClient(model="claude-sonnet-5", api_key="fake-key", client=http_client)


def _ok_response(content: str = '{"summary": "요약"}') -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        },
    )


def test_complete_json_posts_expected_request_shape():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return _ok_response()

    llm = _client_with_transport(handler)
    result = llm.complete_json(system="시스템 지시", prompt="사용자 프롬프트")

    assert result == {"summary": "요약"}
    assert captured["url"] == "https://fake.gateway/v1/gateway/chat/completions/"
    body = captured["body"]
    assert body["model"] == "claude-sonnet-5"
    assert body["temperature"] == 0.0
    assert body["messages"] == [
        {"role": "system", "content": "시스템 지시"},
        {"role": "user", "content": "사용자 프롬프트"},
    ]


def test_complete_json_parses_content_and_records_usage():
    llm = _client_with_transport(lambda request: _ok_response('{"issues": []}'))
    result = llm.complete_json(system="s", prompt="p")

    assert result == {"issues": []}
    assert len(llm.usage) == 1
    assert llm.usage[0].prompt_tokens == 10
    assert llm.usage[0].completion_tokens == 5
    assert llm.usage[0].total_tokens == 15


def test_complete_json_strips_markdown_json_fence():
    llm = _client_with_transport(lambda request: _ok_response('```json\n{"a": 1}\n```'))
    assert llm.complete_json(system="s", prompt="p") == {"a": 1}


def test_complete_json_retries_on_429_then_succeeds(monkeypatch):
    monkeypatch.setattr("planqa_review.llm.gateway.time.sleep", lambda _seconds: None)
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(429, json={"error": "rate limited"})
        return _ok_response()

    llm = _client_with_transport(handler)
    result = llm.complete_json(system="s", prompt="p")

    assert result == {"summary": "요약"}
    assert calls["count"] == 2
    assert len(llm.usage) == 1


def test_complete_json_raises_after_exhausting_retries_on_persistent_5xx(monkeypatch):
    monkeypatch.setattr("planqa_review.llm.gateway.time.sleep", lambda _seconds: None)
    llm = _client_with_transport(lambda request: httpx.Response(503, json={"error": "overloaded"}))

    with pytest.raises(httpx.HTTPStatusError):
        llm.complete_json(system="s", prompt="p")


def test_missing_api_key_raises_clear_error(monkeypatch):
    monkeypatch.delenv("MINDLOGIC_GATEWAY_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="MINDLOGIC_GATEWAY_API_KEY"):
        GatewayClient(model="claude-sonnet-5")
