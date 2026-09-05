"""Minimal PrismTrace (https://blockconvey.com/prismtrace) client.

PrismTrace is an LLM/agent observability platform: it stores a trace of
each real LLM call (prompt, response, latency, tokens) so problems that
only show up in production -- hallucinated numbers, latency spikes, a
model silently falling back -- are visible in a dashboard afterward,
instead of only in whatever terminal happened to be open at the time.

This codebase doesn't use any of PrismTrace's built-in framework
integrations (LangChain, LangGraph, Google ADK, LiteLLM, OpenAI Agents
SDK) -- both real LLM call sites here
(backend/agent_engine/explain.py, backend/agent_engine/narrative_check.py)
call the raw Anthropic SDK directly. So rather than depending on the
prismtrace-sdk package (built around those framework callbacks), this
module posts straight to PrismTrace's documented manual ingest endpoint
(POST /api/traces) -- the same approach PrismTrace's own docs recommend
for "any raw LLM usage."

Fully optional and fail-open: if PRISMTRACE_API_KEY / PRISMTRACE_PROJECT_ID
aren't set, or the network call fails, tracing is silently skipped -- it
must never affect the actual LLM call it's recording, and must never add
latency to the request path it's observing (traces are sent from a
background thread, per PrismTrace's own guidance).
"""

from __future__ import annotations

import os
import threading
import uuid
from typing import Optional

import requests

DEFAULT_HOST = "https://prism.blockconvey.com"
_TIMEOUT_SECONDS = 3
_VERIFY_TIMEOUT_SECONDS = 10


def _enabled() -> bool:
    return bool(os.environ.get("PRISMTRACE_API_KEY") and os.environ.get("PRISMTRACE_PROJECT_ID"))


def _headers() -> dict:
    return {
        "Content-Type": "application/json",
        "X-PRISMtrace-Key": os.environ["PRISMTRACE_API_KEY"],
    }


def _post_trace(payload: dict) -> None:
    host = os.environ.get("PRISMTRACE_HOST", DEFAULT_HOST)
    try:
        requests.post(f"{host}/api/traces", json=payload, headers=_headers(), timeout=_TIMEOUT_SECONDS)
    except Exception:
        # Tracing must never break or slow down the feature it's observing.
        pass


def record_llm_call(
    model: str,
    input_messages: list[dict],
    output_message: str,
    latency_ms: float,
    agent_name: str,
    session_id: Optional[str] = None,
    token_count_input: Optional[int] = None,
    token_count_output: Optional[int] = None,
    metadata: Optional[dict] = None,
    error: Optional[str] = None,
) -> None:
    """Record one real LLM call. No-ops immediately if PrismTrace isn't
    configured (no PRISMTRACE_API_KEY/PROJECT_ID). Otherwise fires the
    actual HTTP POST on a daemon thread so this call returns immediately.

    `agent_name` should be stable across calls from the same code path
    (e.g. "whyledger-explain") -- PrismTrace's Model Inventory groups by
    it, and a changing name makes one agent look like many. `session_id`
    should be shared across calls that belong to the same investigation
    (here, the variance_id) so PrismTrace can assemble them into one
    trace instead of unrelated fragments.
    """
    if not _enabled():
        return

    payload: dict = {
        "project_id": os.environ["PRISMTRACE_PROJECT_ID"],
        "trace_id": str(uuid.uuid4()),
        "model": model,
        "input_messages": input_messages,
        "output_message": output_message,
        "latency_ms": latency_ms,
        "agent_name": agent_name,
        "agent_id": agent_name,
    }
    if session_id is not None:
        payload["session_id"] = session_id
    if token_count_input is not None:
        payload["token_count_input"] = token_count_input
    if token_count_output is not None:
        payload["token_count_output"] = token_count_output
    if metadata is not None or error is not None:
        payload["metadata"] = {**(metadata or {}), **({"error": error} if error else {})}

    threading.Thread(target=_post_trace, args=(payload,), daemon=True).start()


def verify() -> dict:
    """Run the setup-doctor handshake: confirms PRISMTRACE_API_KEY /
    PRISMTRACE_PROJECT_ID are valid and stores one test trace. Returns
    the parsed JSON response, or {"error": ...} if the request itself
    couldn't be made (e.g. credentials unset, no network). Run directly:

        python -m backend.observability.prismtrace_client
    """
    if not _enabled():
        return {"error": "PRISMTRACE_API_KEY and PRISMTRACE_PROJECT_ID must both be set"}
    host = os.environ.get("PRISMTRACE_HOST", DEFAULT_HOST)
    try:
        resp = requests.post(
            f"{host}/api/setup-doctor/handshake",
            json={"project_id": os.environ["PRISMTRACE_PROJECT_ID"], "send_test_trace": True},
            headers=_headers(),
            timeout=_VERIFY_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        return {"error": str(exc)}


if __name__ == "__main__":
    import json

    print(json.dumps(verify(), indent=2))
