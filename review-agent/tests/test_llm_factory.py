from __future__ import annotations

import pytest

from planqa_review.llm.factory import build_llm_client
from planqa_review.llm.gemini import GeminiClient
from planqa_review.llm.ollama import OllamaClient


@pytest.fixture(autouse=True)
def _fake_gemini_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-tests")
    monkeypatch.setenv("MINDLOGIC_GATEWAY_API_KEY", "fake-gateway-key-for-tests")


def test_build_llm_client_defaults_temperature_to_zero():
    llm = build_llm_client("gemini", "fake-model")
    assert llm._temperature == 0.0


def test_build_llm_client_passes_through_explicit_temperature():
    llm = build_llm_client("gemini", "fake-model", temperature=0.7)
    assert llm._temperature == 0.7


def test_build_llm_client_ollama_gets_temperature_too():
    llm = build_llm_client("ollama", "fake-model", temperature=0.3)
    assert isinstance(llm, OllamaClient)
    assert llm._temperature == 0.3


def test_build_llm_client_gateway_gets_temperature_too():
    from planqa_review.llm.gateway import GatewayClient

    llm = build_llm_client("gateway", "claude-sonnet-5", temperature=0.5)
    assert isinstance(llm, GatewayClient)
    assert llm._temperature == 0.5


def test_gemini_client_default_temperature_is_zero():
    llm = GeminiClient(model="fake-model", api_keys=["fake-key"])
    assert llm._temperature == 0.0
