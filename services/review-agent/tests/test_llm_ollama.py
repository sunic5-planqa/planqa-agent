from __future__ import annotations

import httpx

from planqa_review.llm.ollama import OllamaClient


class _FakeResponse:
    def __init__(self, body: dict) -> None:
        self._body = body

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._body


def _message_response(content: str) -> dict:
    return {"message": {"content": content}, "prompt_eval_count": 10, "eval_count": 5}


def test_complete_json_sends_plain_prompt_without_cache_prefix(monkeypatch):
    captured = {}

    def fake_post(url, *, json, timeout):
        captured["messages"] = json["messages"]
        return _FakeResponse(_message_response('{"ok": true}'))

    monkeypatch.setattr(httpx, "post", fake_post)
    llm = OllamaClient()
    result = llm.complete_json(system="s", prompt="원본 프롬프트")

    assert result == {"ok": True}
    assert captured["messages"][1]["content"] == "원본 프롬프트"


def test_complete_json_concatenates_cache_prefix_since_ollama_has_no_caching(monkeypatch):
    # Ollama has no prompt-caching support (only AnthropicClient does) — cache_prefix must
    # still work, just by plain concatenation ahead of prompt, per LLMClient's documented
    # contract ("backends without caching support just concatenate").
    captured = {}

    def fake_post(url, *, json, timeout):
        captured["messages"] = json["messages"]
        return _FakeResponse(_message_response('{"ok": true}'))

    monkeypatch.setattr(httpx, "post", fake_post)
    llm = OllamaClient()
    llm.complete_json(system="s", prompt="카테고리 A", cache_prefix="공유되는 청크 본문")

    assert captured["messages"][1]["content"] == "공유되는 청크 본문\n\n카테고리 A"
