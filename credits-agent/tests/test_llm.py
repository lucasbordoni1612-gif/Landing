"""Request shapes sent to the Claude API, checked with a mock HTTP transport (no network)."""
import json

import anthropic
import httpx2
import pytest
from anthropic import DefaultHttpxClient

from credits_agent.config import LLMConfig
from credits_agent.llm import ClaudeLLM, LLMError, web_search_tool
from credits_agent.schemas import ANSWERS_SCHEMA, CANDIDATES_TOOL


def _client(replies):
    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append((request.headers, body))
        content, stop = replies.pop(0)
        return httpx2.Response(200, json={
            "id": "msg_1", "type": "message", "role": "assistant", "model": body["model"], "content": content,
            "stop_reason": stop, "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1}})

    client = anthropic.Anthropic(api_key="test", http_client=DefaultHttpxClient(transport=httpx2.MockTransport(handler)))
    return client, seen


def test_json_call_uses_structured_output_effort_and_fallback():
    client, seen = _client([([{"type": "text", "text": '{"answers": []}'}], "end_turn")])
    assert ClaudeLLM(LLMConfig(), client).json(purpose="t", system="s", prompt="p", schema=ANSWERS_SCHEMA,
                                               effort="medium") == {"answers": []}
    headers, body = seen[0]
    assert body["model"] == "claude-opus-5-5" and body["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in headers["anthropic-beta"]
    assert body["output_config"]["effort"] == "medium" and body["output_config"]["format"]["type"] == "json_schema"


def test_research_resumes_pause_turn_nudges_and_validates():
    tool_call = [{"type": "tool_use", "id": "toolu_1", "name": "record_program_candidates",
                  "input": {"candidates": []}}]
    client, seen = _client([
        ([{"type": "text", "text": "searching"}], "pause_turn"),
        ([{"type": "text", "text": "done, here is a summary"}], "end_turn"),
        (tool_call, "tool_use"),
    ])
    out = ClaudeLLM(LLMConfig(), client).research(purpose="r", system="s", prompt="p", report_tool=CANDIDATES_TOOL,
                                                  server_tools=[web_search_tool(3)], effort="high")
    assert out == {"candidates": []} and len(seen) == 3
    assert seen[2][1]["messages"][-1]["content"].startswith("Now call the record_program_candidates")

    bad = [{"type": "tool_use", "id": "toolu_2", "name": "record_program_candidates", "input": {"oops": 1}}]
    client, _ = _client([(bad, "tool_use")])
    with pytest.raises(LLMError):
        ClaudeLLM(LLMConfig(), client).research(purpose="r", system="s", prompt="p", report_tool=CANDIDATES_TOOL,
                                                server_tools=[], effort="high")


def test_refusal_raises():
    client, _ = _client([([], "refusal")])
    with pytest.raises(LLMError, match="recusou"):
        ClaudeLLM(LLMConfig(), client).json(purpose="t", system="s", prompt="p", schema=ANSWERS_SCHEMA, effort="low")
