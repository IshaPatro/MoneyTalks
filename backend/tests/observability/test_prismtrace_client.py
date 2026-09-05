"""Tests for the PrismTrace manual-instrumentation client.

The overriding rule: tracing must never affect the thing it's observing.
So every test here checks fail-open behavior (no config -> no-op,
network failure -> swallowed) at least as carefully as the happy path.
"""

import threading
import time

import pytest

from backend.observability import prismtrace_client as ptc


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("PRISMTRACE_API_KEY", raising=False)
    monkeypatch.delenv("PRISMTRACE_PROJECT_ID", raising=False)
    monkeypatch.delenv("PRISMTRACE_HOST", raising=False)


def _wait_for_threads(timeout=1.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not any(t.name.startswith("Thread") and t.is_alive() for t in threading.enumerate()):
            return
        time.sleep(0.01)


def test_record_llm_call_is_noop_without_credentials(monkeypatch):
    calls = []
    monkeypatch.setattr(ptc, "_post_trace", lambda payload: calls.append(payload))

    ptc.record_llm_call(
        model="claude-sonnet-5", input_messages=[{"role": "user", "content": "hi"}],
        output_message="hello", latency_ms=12.0, agent_name="test-agent",
    )
    _wait_for_threads()
    assert calls == []  # no API key/project id set -> nothing sent, not even attempted


def test_record_llm_call_sends_expected_payload(monkeypatch):
    monkeypatch.setenv("PRISMTRACE_API_KEY", "pt-sk-test")
    monkeypatch.setenv("PRISMTRACE_PROJECT_ID", "proj-123")
    captured = {}

    def fake_post(payload):
        captured.update(payload)

    monkeypatch.setattr(ptc, "_post_trace", fake_post)

    ptc.record_llm_call(
        model="claude-sonnet-5",
        input_messages=[{"role": "user", "content": "explain this variance"}],
        output_message="Revenue increased because of X.",
        latency_ms=345.6, agent_name="whyledger-explain", session_id="VAR_001",
        token_count_input=120, token_count_output=40,
        metadata={"account": "ACC-0001"},
    )
    _wait_for_threads()

    assert captured["project_id"] == "proj-123"
    assert captured["model"] == "claude-sonnet-5"
    assert captured["agent_name"] == "whyledger-explain"
    assert captured["agent_id"] == "whyledger-explain"
    assert captured["session_id"] == "VAR_001"
    assert captured["token_count_input"] == 120
    assert captured["token_count_output"] == 40
    assert captured["metadata"] == {"account": "ACC-0001"}
    assert captured["output_message"] == "Revenue increased because of X."
    assert "trace_id" in captured


def test_record_llm_call_includes_error_in_metadata(monkeypatch):
    monkeypatch.setenv("PRISMTRACE_API_KEY", "pt-sk-test")
    monkeypatch.setenv("PRISMTRACE_PROJECT_ID", "proj-123")
    captured = {}
    monkeypatch.setattr(ptc, "_post_trace", lambda payload: captured.update(payload))

    ptc.record_llm_call(
        model="claude-sonnet-5", input_messages=[], output_message="",
        latency_ms=5.0, agent_name="whyledger-explain",
        error="RateLimitError: 429",
    )
    _wait_for_threads()
    assert captured["metadata"]["error"] == "RateLimitError: 429"


def test_post_trace_swallows_network_errors(monkeypatch):
    monkeypatch.setenv("PRISMTRACE_API_KEY", "pt-sk-test")
    monkeypatch.setenv("PRISMTRACE_PROJECT_ID", "proj-123")

    def boom(*args, **kwargs):
        raise ConnectionError("no network")

    monkeypatch.setattr(ptc.requests, "post", boom)
    # must not raise -- tracing failures are never allowed to propagate
    ptc._post_trace({"project_id": "proj-123"})


def test_verify_returns_error_dict_without_credentials():
    result = ptc.verify()
    assert result == {"error": "PRISMTRACE_API_KEY and PRISMTRACE_PROJECT_ID must both be set"}


def test_verify_calls_handshake_endpoint(monkeypatch):
    monkeypatch.setenv("PRISMTRACE_API_KEY", "pt-sk-test")
    monkeypatch.setenv("PRISMTRACE_PROJECT_ID", "proj-123")

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"live_connected": True}

    captured_call = {}

    def fake_post(url, json, headers, timeout):
        captured_call.update(url=url, json=json, headers=headers)
        return FakeResponse()

    monkeypatch.setattr(ptc.requests, "post", fake_post)

    result = ptc.verify()

    assert result == {"live_connected": True}
    assert captured_call["url"] == f"{ptc.DEFAULT_HOST}/api/setup-doctor/handshake"
    assert captured_call["json"] == {"project_id": "proj-123", "send_test_trace": True}
    assert captured_call["headers"]["X-PRISMtrace-Key"] == "pt-sk-test"


def test_verify_returns_error_on_request_failure(monkeypatch):
    monkeypatch.setenv("PRISMTRACE_API_KEY", "pt-sk-test")
    monkeypatch.setenv("PRISMTRACE_PROJECT_ID", "proj-123")
    monkeypatch.setattr(ptc.requests, "post", lambda *a, **k: (_ for _ in ()).throw(ConnectionError("down")))

    result = ptc.verify()
    assert "error" in result


def test_host_override_is_respected(monkeypatch):
    monkeypatch.setenv("PRISMTRACE_API_KEY", "pt-sk-test")
    monkeypatch.setenv("PRISMTRACE_PROJECT_ID", "proj-123")
    monkeypatch.setenv("PRISMTRACE_HOST", "https://custom.example.com")
    seen = {}

    class FakeResponse:
        def raise_for_status(self): pass
        def json(self): return {}

    monkeypatch.setattr(ptc.requests, "post", lambda url, **k: seen.setdefault("url", url) or FakeResponse())
    ptc.verify()
    assert seen["url"] == "https://custom.example.com/api/setup-doctor/handshake"
