"""Standardized LLM factory.

All traffic routes through Lobster Trap (Veea's DPI proxy) at localhost:8080.
Every caller passes a `declared_intent` label so Lobster Trap can compare it
against its detected intent — a mismatch flags a disguised adversarial prompt.

Declared intents used in this system:
  medical_drug_safety  — medical agent querying for drug interactions
  intent_check         — orchestrator classifying the user's query
  safety_judge         — input/output guardrail LLM judges

Backend: HuggingFace featherless-ai provider (OpenAI-compatible, free tier)
Launch Lobster Trap: ./lobstertrap serve --backend https://router.huggingface.co/featherless-ai --policy configs/lobster_policy.yaml
"""
from typing import Literal, Type, TypeVar

from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from app.config.settings import settings

DeclaredIntent = Literal["medical_drug_safety", "intent_check", "safety_judge"]

T = TypeVar("T", bound=BaseModel)


def get_llm(
    declared_intent: DeclaredIntent = "medical_drug_safety",
    temperature: float = 0.1,
    max_tokens: int = 512,
) -> ChatOpenAI:
    """
    Returns a ChatOpenAI client pointed at Lobster Trap.

    `declared_intent` is forwarded via `_lobstertrap` extra_body so the proxy
    can detect declared-vs-actual intent mismatches — a core security signal.
    """
    return ChatOpenAI(
        model=settings.LLM_MODEL_ID,
        base_url=settings.VEEA_ENDPOINT,
        api_key=settings.HUGGINGFACE_TOKEN,
        temperature=temperature,
        max_tokens=max_tokens,
        extra_body={
            "_lobstertrap": {
                "declared_intent": declared_intent,
                "app": "clinical-discharge-orchestrator",
                "policy": "clinical-agent-hipaa",
            }
        },
    )


def get_structured_llm(
    schema: Type[T],
    declared_intent: DeclaredIntent = "safety_judge",
    temperature: float = 0.1,
):
    """
    Returns an LLM that emits a parsed Pydantic instance of `schema` instead
    of free-form text. Wraps `.with_structured_output()` so callers get type
    safety; the calling node must still try/except in case the model refuses
    to comply with the schema.
    """
    return get_llm(declared_intent=declared_intent, temperature=temperature).with_structured_output(schema)
