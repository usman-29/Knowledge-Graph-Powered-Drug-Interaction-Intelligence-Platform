"""
Deterministic regex patterns used by the input/output guardrails.

These are intentionally conservative — false positives are preferable to leaks
in a regulated clinical context. The LLM-based detectors run *after* these
deterministic filters and only on text that survives them.
"""
import re

PII_PATTERNS: dict[str, re.Pattern] = {
    "SSN": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "EMAIL": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    "PHONE": re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
    "MRN": re.compile(r"\bMRN[:\s#]*\d{5,}\b", re.IGNORECASE),
    "DOB": re.compile(r"\b(?:0?[1-9]|1[0-2])[/-](?:0?[1-9]|[12]\d|3[01])[/-](?:19|20)\d{2}\b"),
    "CREDIT_CARD": re.compile(r"\b(?:\d[ -]*?){13,16}\b"),
}

INJECTION_PATTERNS: list[re.Pattern] = [
    re.compile(r"ignore (?:all |the )?(?:previous|prior|above)\s+(?:instructions?|prompts?|rules?)", re.IGNORECASE),
    re.compile(r"disregard (?:all |the )?(?:previous|prior|above)\s+(?:instructions?|prompts?)", re.IGNORECASE),
    re.compile(r"you are now\s+(?:a |an )?(?:dan|jailbroken|unrestricted)", re.IGNORECASE),
    re.compile(r"forget\s+(?:everything|all|your)\s+(?:instructions?|rules?|guidelines?)", re.IGNORECASE),
    re.compile(r"system\s*prompt\s*[:=]", re.IGNORECASE),
    re.compile(r"developer\s*mode", re.IGNORECASE),
    re.compile(r"act\s+as\s+(?:if\s+)?(?:you\s+(?:are|were)\s+)?(?:no longer|not)\s+bound", re.IGNORECASE),
    re.compile(r"reveal\s+(?:your|the)\s+(?:system\s+)?prompt", re.IGNORECASE),
    re.compile(r"<\s*\|?\s*(?:im_start|im_end|system|assistant)\s*\|?\s*>", re.IGNORECASE),
]

JAILBREAK_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(?:dan|do anything now)\b", re.IGNORECASE),
    re.compile(r"pretend\s+(?:you\s+(?:are|have)|to\s+be)", re.IGNORECASE),
    re.compile(r"roleplay\s+as", re.IGNORECASE),
    re.compile(r"hypothetically.*(?:without|no)\s+(?:safety|restriction|filter)", re.IGNORECASE),
]

OFF_TOPIC_TRIPWIRES: list[re.Pattern] = [
    re.compile(r"\b(?:write|generate)\s+(?:code|script|program)\b", re.IGNORECASE),
    re.compile(r"\btell\s+me\s+a\s+joke\b", re.IGNORECASE),
    re.compile(r"\b(?:stock|crypto|investment)\s+(?:price|tip|advice)\b", re.IGNORECASE),
]
