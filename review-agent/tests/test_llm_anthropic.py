from __future__ import annotations

import httpx
import pytest
from anthropic import APIConnectionError, APIStatusError
from anthropic.types import Message, TextBlock, ThinkingBlock, Usage

from planqa_review.llm.anthropic import AnthropicClient


def _status_error(status_code: int) -> APIStatusError:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(status_code, request=request)
    return APIStatusError("boom", response=response, body=None)


def _connection_error() -> APIConnectionError:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return APIConnectionError(request=request)


def _message(content: str, input_tokens: int = 10, output_tokens: int = 5) -> Message:
    return Message(
        id="msg_1",
        type="message",
        role="assistant",
        model="claude-sonnet-5",
        content=[TextBlock(type="text", text=content)],
        stop_reason="end_turn",
        usage=Usage(input_tokens=input_tokens, output_tokens=output_tokens),
    )


class _FakeMessages:
    def __init__(self, handler) -> None:
        self._handler = handler
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._handler(kwargs)


class _FakeAnthropic:
    def __init__(self, handler) -> None:
        self.messages = _FakeMessages(handler)


def _client_with_handler(handler) -> tuple[AnthropicClient, _FakeAnthropic]:
    fake = _FakeAnthropic(handler)
    llm = AnthropicClient(model="claude-sonnet-5", api_key="fake-key", client=fake)
    return llm, fake


def test_complete_json_posts_expected_request_shape():
    llm, fake = _client_with_handler(lambda kwargs: _message('{"summary": "요약"}'))
    result = llm.complete_json(system="시스템 지시", prompt="사용자 프롬프트")

    assert result == {"summary": "요약"}
    assert len(fake.messages.calls) == 1
    call = fake.messages.calls[0]
    assert call["model"] == "claude-sonnet-5"
    assert "temperature" not in call  # rejected outright by claude-sonnet-5 — see anthropic.py
    assert call["thinking"] == {"type": "disabled"}
    # system is always sent as a cache-breakpoint block — it's static per-caller text in
    # this codebase, so caching it is free and pays off across every call, not just one.
    assert call["system"] == [{"type": "text", "text": "시스템 지시", "cache_control": {"type": "ephemeral"}}]
    assert call["messages"] == [{"role": "user", "content": "사용자 프롬프트"}]


def test_complete_json_splits_cache_prefix_into_its_own_cached_block():
    llm, fake = _client_with_handler(lambda kwargs: _message('{"summary": "요약"}'))
    llm.complete_json(system="s", prompt="카테고리별 룰", cache_prefix="공유되는 문서 청크 본문")

    call = fake.messages.calls[0]
    assert call["messages"] == [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "공유되는 문서 청크 본문", "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": "카테고리별 룰"},
            ],
        }
    ]


def test_complete_json_without_cache_prefix_sends_plain_string_content():
    llm, fake = _client_with_handler(lambda kwargs: _message('{"summary": "요약"}'))
    llm.complete_json(system="s", prompt="프롬프트만")

    call = fake.messages.calls[0]
    assert call["messages"] == [{"role": "user", "content": "프롬프트만"}]


def test_complete_json_parses_content_and_records_usage():
    llm, _ = _client_with_handler(lambda kwargs: _message('{"issues": []}', input_tokens=10, output_tokens=5))
    result = llm.complete_json(system="s", prompt="p")

    assert result == {"issues": []}
    assert len(llm.usage) == 1
    assert llm.usage[0].prompt_tokens == 10
    assert llm.usage[0].completion_tokens == 5
    assert llm.usage[0].total_tokens == 15


def test_complete_json_strips_markdown_json_fence():
    llm, _ = _client_with_handler(lambda kwargs: _message('```json\n{"a": 1}\n```'))
    assert llm.complete_json(system="s", prompt="p") == {"a": 1}


def test_complete_json_finds_text_block_after_a_leading_thinking_block():
    """claude-sonnet-5 with extended thinking puts a ThinkingBlock before the text block —
    seen live in the demo smoke test, where content[0].text crashed with AttributeError."""

    def message_with_thinking(content: str) -> Message:
        message = _message(content)
        return message.model_copy(
            update={"content": [ThinkingBlock(type="thinking", thinking="음, 확인해보자", signature="sig"), *message.content]}
        )

    llm, _ = _client_with_handler(lambda kwargs: message_with_thinking('{"summary": "요약"}'))
    assert llm.complete_json(system="s", prompt="p") == {"summary": "요약"}


def test_complete_json_retries_on_429_then_succeeds(monkeypatch):
    monkeypatch.setattr("planqa_review.llm.anthropic.time.sleep", lambda _seconds: None)
    calls = {"count": 0}

    def handler(kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise _status_error(429)
        return _message('{"summary": "요약"}')

    llm, _ = _client_with_handler(handler)
    result = llm.complete_json(system="s", prompt="p")

    assert result == {"summary": "요약"}
    assert calls["count"] == 2
    assert len(llm.usage) == 1


def test_complete_json_raises_after_exhausting_retries_on_persistent_5xx(monkeypatch):
    monkeypatch.setattr("planqa_review.llm.anthropic.time.sleep", lambda _seconds: None)

    def handler(kwargs):
        raise _status_error(503)

    llm, _ = _client_with_handler(handler)
    with pytest.raises(APIStatusError):
        llm.complete_json(system="s", prompt="p")


def test_complete_json_reraises_non_retryable_error_immediately():
    def handler(kwargs):
        raise _status_error(400)

    llm, fake = _client_with_handler(handler)
    with pytest.raises(APIStatusError):
        llm.complete_json(system="s", prompt="p")
    assert len(fake.messages.calls) == 1


def test_temperature_is_sent_for_models_that_accept_it():
    fake = _FakeAnthropic(lambda kwargs: _message('{"summary": "요약"}'))
    llm = AnthropicClient(model="claude-3-5-haiku-20241022", api_key="fake-key", temperature=0.7, client=fake)
    llm.complete_json(system="s", prompt="p")

    call = fake.messages.calls[0]
    assert call["temperature"] == 0.7


def test_complete_json_retries_on_connection_error_then_succeeds(monkeypatch):
    monkeypatch.setattr("planqa_review.llm.anthropic.time.sleep", lambda _seconds: None)
    calls = {"count": 0}

    def handler(kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise _connection_error()
        return _message('{"summary": "요약"}')

    llm, _ = _client_with_handler(handler)
    result = llm.complete_json(system="s", prompt="p")

    assert result == {"summary": "요약"}
    assert calls["count"] == 2


def test_complete_json_raises_after_exhausting_retries_on_persistent_connection_error(monkeypatch):
    monkeypatch.setattr("planqa_review.llm.anthropic.time.sleep", lambda _seconds: None)

    def handler(kwargs):
        raise _connection_error()

    llm, _ = _client_with_handler(handler)
    with pytest.raises(APIConnectionError):
        llm.complete_json(system="s", prompt="p")


def test_missing_api_key_raises_clear_error(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        AnthropicClient(model="claude-sonnet-5")
