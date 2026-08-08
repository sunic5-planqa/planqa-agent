from __future__ import annotations

import pytest

from planqa_eval.llm.gemini import _load_api_keys


def test_explicit_keys_take_precedence(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEYS", "env-a,env-b")
    monkeypatch.setenv("GEMINI_API_KEY", "env-single")
    assert _load_api_keys(["explicit-key"]) == ["explicit-key"]


def test_multi_key_env_var_is_split_and_stripped(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEYS", " key-one, key-two ,key-three")
    assert _load_api_keys(None) == ["key-one", "key-two", "key-three"]


def test_falls_back_to_single_key_env_var(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEYS", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "solo-key")
    assert _load_api_keys(None) == ["solo-key"]


def test_raises_when_no_key_configured(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEYS", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        _load_api_keys(None)
