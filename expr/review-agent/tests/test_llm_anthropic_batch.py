from __future__ import annotations

from types import SimpleNamespace

from planqa_review.llm.anthropic import build_batch_request, cancel_batch, fetch_batch_results, poll_batch, submit_batch


def _counts(*, processing=0, succeeded=0, errored=0, canceled=0, expired=0) -> SimpleNamespace:
    return SimpleNamespace(processing=processing, succeeded=succeeded, errored=errored, canceled=canceled, expired=expired)


class _FakeBatches:
    def __init__(self) -> None:
        self.created_requests: list = None
        self.canceled_ids: list[str] = []
        self._retrieve_response = None
        self._results_response: list = []

    def create(self, *, requests):
        self.created_requests = requests
        return SimpleNamespace(id="batch_123")

    def retrieve(self, batch_id):
        return self._retrieve_response

    def cancel(self, batch_id):
        self.canceled_ids.append(batch_id)

    def results(self, batch_id):
        return iter(self._results_response)


class _FakeAnthropicBatchClient:
    def __init__(self) -> None:
        self.messages = SimpleNamespace(batches=_FakeBatches())


def _text_message(text: str):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])


def test_build_batch_request_matches_complete_json_message_shape():
    req = build_batch_request("doc-1", "sys", "prompt text", model="claude-sonnet-5")
    assert req["custom_id"] == "doc-1"
    assert req["params"]["model"] == "claude-sonnet-5"
    assert "temperature" not in req["params"]  # claude-sonnet-5 rejects it, same as complete_json
    assert req["params"]["system"] == [{"type": "text", "text": "sys", "cache_control": {"type": "ephemeral"}}]
    assert req["params"]["messages"] == [{"role": "user", "content": "prompt text"}]


def test_build_batch_request_sends_temperature_for_models_that_accept_it():
    req = build_batch_request("doc-1", "sys", "p", model="claude-3-5-haiku-20241022", temperature=0.3)
    assert req["params"]["temperature"] == 0.3


def test_build_batch_request_splits_cache_prefix_into_its_own_block():
    req = build_batch_request("doc-1", "sys", "prompt", cache_prefix="rule block")
    assert req["params"]["messages"] == [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "rule block", "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": "prompt"},
            ],
        }
    ]


def test_submit_batch_returns_the_batch_id():
    client = _FakeAnthropicBatchClient()
    requests = [build_batch_request("doc-1", "sys", "p")]
    batch_id = submit_batch(client, requests)
    assert batch_id == "batch_123"
    assert client.messages.batches.created_requests == requests


def test_poll_batch_reports_not_done_while_processing():
    client = _FakeAnthropicBatchClient()
    client.messages.batches._retrieve_response = SimpleNamespace(
        processing_status="in_progress", request_counts=_counts(processing=5, succeeded=15)
    )
    done, counts = poll_batch(client, "batch_123")
    assert done is False
    assert counts["processing"] == 5
    assert counts["succeeded"] == 15


def test_poll_batch_reports_done_when_ended():
    client = _FakeAnthropicBatchClient()
    client.messages.batches._retrieve_response = SimpleNamespace(
        processing_status="ended", request_counts=_counts(succeeded=20)
    )
    done, counts = poll_batch(client, "batch_123")
    assert done is True
    assert counts["succeeded"] == 20


def test_cancel_batch_calls_through_with_the_batch_id():
    client = _FakeAnthropicBatchClient()
    cancel_batch(client, "batch_123")
    assert client.messages.batches.canceled_ids == ["batch_123"]


def test_fetch_batch_results_parses_succeeded_entries_by_custom_id():
    client = _FakeAnthropicBatchClient()
    client.messages.batches._results_response = [
        SimpleNamespace(custom_id="DOC-001", result=SimpleNamespace(type="succeeded", message=_text_message('{"a": 1}'))),
        SimpleNamespace(custom_id="DOC-002", result=SimpleNamespace(type="succeeded", message=_text_message('{"b": 2}'))),
    ]
    results = fetch_batch_results(client, "batch_123")
    assert results == {"DOC-001": {"a": 1}, "DOC-002": {"b": 2}}


def test_fetch_batch_results_marks_non_succeeded_entries_as_none():
    client = _FakeAnthropicBatchClient()
    client.messages.batches._results_response = [
        SimpleNamespace(custom_id="DOC-001", result=SimpleNamespace(type="errored")),
        SimpleNamespace(custom_id="DOC-002", result=SimpleNamespace(type="canceled")),
        SimpleNamespace(custom_id="DOC-003", result=SimpleNamespace(type="expired")),
    ]
    results = fetch_batch_results(client, "batch_123")
    assert results == {"DOC-001": None, "DOC-002": None, "DOC-003": None}


def test_fetch_batch_results_marks_malformed_succeeded_json_as_none():
    client = _FakeAnthropicBatchClient()
    client.messages.batches._results_response = [
        SimpleNamespace(custom_id="DOC-001", result=SimpleNamespace(type="succeeded", message=_text_message("not json"))),
    ]
    results = fetch_batch_results(client, "batch_123")
    assert results == {"DOC-001": None}


def test_fetch_batch_results_marks_succeeded_entry_with_no_text_block_as_none():
    client = _FakeAnthropicBatchClient()
    no_text_message = SimpleNamespace(content=[SimpleNamespace(type="thinking", text="음...")])
    client.messages.batches._results_response = [
        SimpleNamespace(custom_id="DOC-001", result=SimpleNamespace(type="succeeded", message=no_text_message)),
    ]
    results = fetch_batch_results(client, "batch_123")
    assert results == {"DOC-001": None}
