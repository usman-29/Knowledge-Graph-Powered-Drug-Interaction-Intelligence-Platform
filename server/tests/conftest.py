"""
Shared fixtures for the test suite.

The guardrail and RBAC tests are deterministic (no LLM needed).
Pipeline tests mock the LLM + Neo4j so CI can run without external services.
"""
import pytest
from unittest.mock import MagicMock, patch
from langchain_core.messages import HumanMessage, AIMessage


def _make_ai_msg(content: str, tool_calls: list | None = None) -> AIMessage:
    msg = AIMessage(content=content)
    msg.tool_calls = tool_calls or []
    return msg


@pytest.fixture
def mock_llm():
    """LLM that immediately returns a clean CLEAN label (for guardrail judges)."""
    m = MagicMock()
    m.invoke.return_value = _make_ai_msg("CLEAN")
    return m


@pytest.fixture
def mock_llm_medical():
    """LLM that returns a final answer with no tool calls (medical agent)."""
    m = MagicMock()
    m.bind_tools.return_value = m
    m.invoke.return_value = _make_ai_msg(
        "Based on local database findings, Aspirin interacts with Warfarin."
    )
    return m


@pytest.fixture
def clean_state():
    return {
        "messages": [HumanMessage(content="Does aspirin interact with warfarin?")],
        "trace_id": "test-trace",
        "user_id": "clinician_1",
        "audit_log": [],
        "blocked": False,
    }
