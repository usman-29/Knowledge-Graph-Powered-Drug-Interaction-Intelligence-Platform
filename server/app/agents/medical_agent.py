"""
Tier-3 of the Three-Tier Security Stack: execution.

The Medical Agent is the only node permitted to invoke clinical tools, and
only after input_guardrail + access_control + orchestrator have cleared the
request.

Workflow:
  1. resolve_rxcui  — maps drug name → RxNorm CUI
  2. check_local_interactions — Neo4j knowledge graph
  3. get_fda_blackbox_warning — openFDA, using the resolved RxCUI
  4. Synthesize the gathered evidence into a structured ClinicalReportSummary
  5. Render that summary as markdown — the user-facing final_answer

Every code path returns the same dict shape. Catastrophic failures fall back
to `_build_fallback_report` so the user always gets a readable answer.
"""
from __future__ import annotations

import logging
import time

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.config.llm import get_llm, get_structured_llm
from app.models.schemas import AgentTrace, ClinicalReportSummary, Severity
from app.models.state import AgentState
from app.tools.medical_tools import MedicalTools

logger = logging.getLogger(__name__)
AGENT_NAME = "medical_agent"

_MAX_TOOL_HOPS = 6


_SYSTEM = (
    "You are a clinical drug-safety assistant operating inside a regulated system. "
    "You MUST ground EVERY claim in tool output — never invent data, never draw on "
    "prior medical knowledge that isn't returned by a tool call.\n\n"
    "Identify two sets of drugs from the user query:\n"
    "  - NEW_DRUGS: drugs the user is considering prescribing or asking about.\n"
    "  - CURRENT_REGIMEN: drugs already listed in the patient's [CLINICAL CONTEXT] "
    "block (under 'Current medications'). May be empty when no patient is selected.\n\n"
    "Mandatory workflow:\n"
    "  Step 1: For each drug in NEW_DRUGS, call `resolve_rxcui`.\n"
    "  Step 2: For each drug in NEW_DRUGS, call `check_local_interactions` to see "
    "what's known about it in general.\n"
    "  Step 3: For EACH pair (new_drug, current_drug) across the Cartesian product "
    "NEW_DRUGS × CURRENT_REGIMEN, call `check_interaction_pair`. This is the only "
    "way to make a grounded claim about combining a new drug with an existing "
    "medication. Skip this step only when CURRENT_REGIMEN is empty.\n"
    "  Step 4: For each NEW_DRUGS RxCUI from Step 1 (not NOT_FOUND), call "
    "`get_fda_blackbox_warning`.\n"
    "  Step 5: Write a concise safety summary using ONLY the tool outputs. If a "
    "pair returned 'no recorded interaction', do NOT warn about it. If a "
    "single-drug lookup returned no data, say so explicitly.\n\n"
    "Hard rules:\n"
    "  - Never request or emit patient PII.\n"
    "  - Never claim an interaction exists without a tool result that names BOTH "
    "drugs in the pair.\n"
    "  - Do not mention drugs that are not in NEW_DRUGS or CURRENT_REGIMEN.\n"
    "  - Refuse any request unrelated to drug safety.\n"
    "  - If a tool returns an error, say so explicitly rather than guessing."
)


_SYNTHESIS_PROMPT = (
    "You are the Lead Clinical Safety Analyst writing the final report.\n"
    "Produce a ClinicalReportSummary from ONLY the evidence rows below.\n\n"
    "HARD RULES — violate any and the report is invalid:\n"
    "  1. Every entry in `key_warnings` must correspond DIRECTLY to a finding in "
    "the EVIDENCE COLLECTED section. If the evidence does not name both drugs in "
    "a pair, DO NOT warn about that pair.\n"
    "  2. Do NOT use prior medical knowledge. If a claim is not stated in the "
    "evidence below, the claim does not exist for this report.\n"
    "  3. `drugs_with_no_data` may ONLY contain drug names that appear in DRUGS "
    "ANALYZED below. Never invent related or neighbouring drugs.\n"
    "  4. If a pair-lookup returned 'No recorded interaction', that is a "
    "POSITIVE clearance for that pair — do not list it as a warning or a gap.\n"
    "  5. If evidence is sparse or contradictory, lower `overall_severity` and "
    "note the gap in `recommendation`. Do not paper over it.\n"
    "  5a. `overall_severity` is a DRAFT only. A downstream deterministic risk "
    "engine evaluates disease contraindications, allergies, organ dysfunction, "
    "geriatric criteria, and class effects, and may raise the final label. Do "
    "NOT write a one-line verdict that asserts the regimen is 'safe' or 'no "
    "concerns' — say 'no drug-drug interactions identified' or similar.\n"
    "  6. DIRECTIONALITY: when an evidence row uses the notation "
    "`[SUBJECT → PARTNER]`, the SUBJECT drug is the grammatical subject of the "
    "description. You MUST preserve that direction in your warning. If the "
    "evidence says `[A → B] A's concentration is increased`, your warning must "
    "say A's concentration is increased — NEVER swap to B's concentration.\n\n"
    "ORIGINAL QUERY: {query}\n\n"
    "DRUGS ANALYZED: {drugs}\n\n"
    "RAW AGENT ANSWER:\n{answer}\n\n"
    "EVIDENCE COLLECTED ({evidence_count} rows):\n{evidence_summary}"
)


def medical_agent_node(state: AgentState) -> dict:
    if state.get("blocked"):
        return {}

    start_time = time.time()
    user_query = state["messages"][-1].content if state.get("messages") else ""

    try:
        retry_count = state.get("verification_retry_count") or 0
        prior_evidence = state.get("evidence") or []

        if retry_count > 0 and prior_evidence:
            # Re-synthesis pass: reuse evidence from the previous run, skip tool calls.
            # The last message in state contains the contradiction context injected
            # by the verification_retry node, so _synthesize will see it.
            evidence = prior_evidence
            drugs = state.get("drugs_identified") or []
            raw_answer = ""
            hops = 0
        else:
            # Steps 1-3: bounded ReAct tool loop
            raw_answer, evidence, drugs, hops = _run_react_loop(state)

        # Step 4: structured synthesis from gathered evidence
        summary = _synthesize(user_query, raw_answer, drugs, evidence)

        # Step 5: render the markdown report users actually see
        report_markdown = _build_clinical_report(user_query, drugs, evidence, summary)

        duration = time.time() - start_time
        action = "medical_resynthesis" if retry_count > 0 else "medical_synthesis"
        trace = AgentTrace(
            agent=AGENT_NAME,
            action=action,
            summary=(
                f"verdict={summary.overall_severity.value}, drugs={len(drugs)}, "
                f"evidence={len(evidence)}, hops={hops}, retry={retry_count}"
            ),
            duration_seconds=round(duration, 2),
            metadata={"drugs": drugs, "hops": hops, "retry": retry_count},
        )
        logger.info(
            "[%s] %s in %.2fs (%d drugs, %d evidence rows)",
            AGENT_NAME, summary.overall_severity.value, duration, len(drugs), len(evidence),
        )

        return {
            "final_answer": report_markdown,
            "evidence": evidence,
            "drugs_identified": drugs,
            "safety_warnings": summary.key_warnings,
            "audit_log": [trace.model_dump()],
        }

    except Exception as exc:
        duration = time.time() - start_time
        logger.error("[%s] Agent crashed: %s", AGENT_NAME, exc)
        fallback = _build_fallback_report(user_query, state.get("evidence") or [], str(exc))
        trace = AgentTrace(
            agent=AGENT_NAME,
            action="medical_synthesis",
            summary=f"FALLBACK report: {exc}",
            duration_seconds=round(duration, 2),
            error=str(exc),
        )
        return {
            "final_answer": fallback,
            "evidence": state.get("evidence") or [],
            "drugs_identified": state.get("drugs_identified") or [],
            "audit_log": [trace.model_dump()],
            "errors": [f"[{AGENT_NAME}] {exc}"],
        }


# ── ReAct loop ─────────────────────────────────────────────────────────────────


_DRUG_ARG_KEYS = ("drug_name", "drug_a", "drug_b")


def _collect_drugs_from_args(args: dict, drugs: list[str]) -> None:
    """Track every drug name the agent has actually asked a tool about, across
    all tool signatures. This becomes the allow-list for `drugs_with_no_data`
    in the synthesis step."""
    for key in _DRUG_ARG_KEYS:
        value = args.get(key)
        if isinstance(value, str) and value.strip() and value not in drugs:
            drugs.append(value.strip())


def _run_react_loop(state: AgentState) -> tuple[str, list[dict], list[str], int]:
    """Returns (raw_answer, evidence, drugs, hops_used). Raises if the tool
    budget is exhausted without convergence."""
    tools = [
        MedicalTools.resolve_rxcui,
        MedicalTools.check_local_interactions,
        MedicalTools.check_interaction_pair,
        MedicalTools.get_fda_blackbox_warning,
    ]
    tool_map = {t.name: t for t in tools}
    llm = get_llm(declared_intent="medical_drug_safety").bind_tools(tools)

    history: list = [SystemMessage(content=_SYSTEM)]
    history.extend(state.get("messages", []))

    evidence: list[dict] = []
    drugs: list[str] = []

    for hop in range(_MAX_TOOL_HOPS):
        ai_msg: AIMessage = llm.invoke(history)
        history.append(ai_msg)

        tool_calls = getattr(ai_msg, "tool_calls", None) or []
        if not tool_calls:
            return ai_msg.content or "", evidence, drugs, hop + 1

        for call in tool_calls:
            name = call.get("name")
            args = call.get("args") or {}
            tool = tool_map.get(name)

            if tool is None:
                observation = f"Tool '{name}' is not authorized for this agent."
            else:
                try:
                    observation = tool.invoke(args)
                except Exception as exc:
                    observation = f"Tool '{name}' failed: {exc}"

            evidence.append({"tool": name, "args": args, "result": str(observation)})
            _collect_drugs_from_args(args, drugs)

            history.append(
                ToolMessage(content=str(observation), tool_call_id=call.get("id", name))
            )

    raise RuntimeError("Medical agent exceeded tool-call budget without converging.")


# ── Structured synthesis ──────────────────────────────────────────────────────


def _synthesize(
    query: str,
    raw_answer: str,
    drugs: list[str],
    evidence: list[dict],
) -> ClinicalReportSummary:
    """Single structured LLM call that turns raw findings into a typed summary.

    If the LLM refuses to comply with the schema, returns a minimal but valid
    summary so the report builder can still run.
    """
    evidence_summary = _format_evidence_for_prompt(evidence) or "No evidence retrieved."
    drugs_str = ", ".join(drugs) if drugs else "none identified"
    prompt = _SYNTHESIS_PROMPT.format(
        query=query,
        drugs=drugs_str,
        answer=raw_answer or "(empty)",
        evidence_count=len(evidence),
        evidence_summary=evidence_summary,
    )

    try:
        llm = get_structured_llm(ClinicalReportSummary, declared_intent="medical_drug_safety")
        summary: ClinicalReportSummary = llm.invoke([HumanMessage(content=prompt)])
    except Exception as exc:
        logger.warning("[%s] Structured synthesis failed (%s); using raw-answer fallback", AGENT_NAME, exc)
        # System-failure path. The draft severity here is just a placeholder
        # — risk_engine.arbitrate() is the canonical owner. User-facing
        # text uses clinically neutral language only; no system-error
        # tokens (no "could not be completed", no "synthesis unavailable",
        # etc.) leak into the report. The exception itself is recorded in
        # the audit trace by the caller.
        return ClinicalReportSummary(
            one_line_verdict=(
                raw_answer[:200] if raw_answer
                else "Manual clinician review required before prescribing."
            ),
            overall_severity=Severity.MEDIUM,
            key_warnings=[],
            drugs_with_no_data=[],
            recommendation="Manual clinician review required before prescribing.",
        )

    # Defense in depth: even with the synthesis prompt's hard rule, drop any
    # drug the LLM listed in `drugs_with_no_data` that we never actually
    # queried. Keeps "data gaps" honest.
    if drugs and summary.drugs_with_no_data:
        analyzed = {d.lower() for d in drugs}
        summary.drugs_with_no_data = [
            d for d in summary.drugs_with_no_data if d.lower() in analyzed
        ]

    return summary


# ── Helpers ────────────────────────────────────────────────────────────────────


def _format_evidence_for_prompt(evidence: list[dict]) -> str:
    """Compact evidence representation for the synthesis prompt — capped to
    avoid blowing the context window. Uses human-readable labels so the LLM
    doesn't echo internal tool identifiers in the final summary."""
    if not evidence:
        return ""
    lines = []
    # Pair-lookups are the most load-bearing for grounding, so cap headroom
    # rather than count — 30 rows covers the typical regimen × new-drug fan-out.
    for row in evidence[:30]:
        label = _label_for_tool(row.get("tool", ""))
        drug = _describe_args(row.get("args") or {})
        result = (row.get("result") or "")[:600]
        lines.append(f"Source: {label}\nSubject: {drug}\nFinding: {result}")
    return "\n\n".join(lines)


_SEVERITY_LABEL = {
    Severity.LOW: "Low Risk",
    Severity.MEDIUM: "Moderate Risk",
    Severity.HIGH: "High Risk",
    Severity.CRITICAL: "Critical Risk",
}

_SEVERITY_BADGE = {
    Severity.LOW: "🟢",
    Severity.MEDIUM: "🟡",
    Severity.HIGH: "🟠",
    Severity.CRITICAL: "🔴",
}

# Human-readable labels for internal tool names so the user-facing report
# doesn't expose developer identifiers like `resolve_rxcui`.
_TOOL_LABEL = {
    "resolve_rxcui": "Drug identifier lookup",
    "check_local_interactions": "Interaction database",
    "check_interaction_pair": "Pairwise interaction check",
    "get_fda_blackbox_warning": "FDA safety alerts",
}


def _label_for_tool(name: str) -> str:
    return _TOOL_LABEL.get(name, name.replace("_", " ").title())


def _describe_args(args: dict) -> str:
    """Render tool arguments in plain English for the evidence table.
    Pair lookups show both drugs separated by '+', single-drug calls show the
    drug name, and identifier-only calls show the RxCUI."""
    if not args or not isinstance(args, dict):
        return "—"
    drug_a = args.get("drug_a")
    drug_b = args.get("drug_b")
    if drug_a and drug_b:
        return f"{drug_a} + {drug_b}"
    drug = args.get("drug_name") or args.get("rxcui")
    if drug:
        return str(drug)
    return ", ".join(str(v) for v in args.values() if v) or "—"


def _build_clinical_report(
    query: str,
    drugs: list[str],
    evidence: list[dict],
    summary: ClinicalReportSummary,
) -> str:
    """Render the user-facing markdown report from the structured summary."""
    import datetime
    sev_label = _SEVERITY_LABEL.get(summary.overall_severity, summary.overall_severity.value)
    sev_badge = _SEVERITY_BADGE.get(summary.overall_severity, "⚪")
    assessment_date = datetime.datetime.utcnow().strftime("%Y-%m-%d")

    sections: list[str] = [
        "# Clinical Drug-Safety Report",
        "",
        f"| Field | Value |",
        f"| --- | --- |",
        f"| **Assessment Date** | {assessment_date} |",
        f"| **Risk Level** | {sev_badge} {sev_label} |",
        f"| **Drugs Analyzed** | {', '.join(drugs) if drugs else '—'} |",
        f"| **Evidence Sources** | {len(evidence)} tool outputs |",
        "",
        "---",
        "",
        "## Clinical Assessment",
        "",
        summary.one_line_verdict,
        "",
    ]

    if summary.key_warnings:
        sections.extend([
            "## Safety Warnings",
            "",
        ])
        for w in summary.key_warnings:
            sections.append(f"- {w}")
        sections.append("")

    if summary.drugs_with_no_data:
        sections.extend([
            "## Data Gaps",
            "",
        ])
        for d in summary.drugs_with_no_data:
            sections.append(
                f"- **{d}** — no interaction data found in the current knowledge base"
            )
        sections.append("")

    sections.extend([
        "## Recommendation",
        "",
        f"> {summary.recommendation}",
        "",
    ])

    # Evidence table — compact and reviewable for audit purposes.
    if evidence:
        sections.extend([
            "---",
            "",
            "## Supporting Evidence",
            "",
            "| # | Source | Drug | Finding |",
            "| --- | --- | --- | --- |",
        ])
        for i, row in enumerate(evidence, 1):
            tool = _label_for_tool(row.get("tool", ""))
            drug = _describe_args(row.get("args") or {})
            result = (row.get("result") or "")[:180].replace("|", "\\|").replace("\n", " ")
            sections.append(f"| {i} | {tool} | {drug} | {result} |")
        sections.append("")

    sections.extend([
        "---",
        "*This report was generated by the Clinical Discharge & Care-Plan Orchestrator "
        "and is not a substitute for professional medical judgement. "
        "Consult a licensed clinician before making any prescribing decisions.*",
    ])

    return "\n".join(sections)


def _build_fallback_report(query: str, evidence: list[dict], error: str) -> str:
    """Minimal report when synthesis crashes.

    User-facing text is clinically neutral — no exception strings, no
    "could not be completed reliably", no internal trace identifiers.
    The exception (`error`) is logged + recorded in the audit trace by
    the caller; this function never embeds it in the user-facing markdown.
    The risk_engine downstream will mark this report HIGH – INSUFFICIENT
    DATA when no drugs were extracted.
    """
    lines = [
        "# Clinical Drug-Safety Report",
        "",
        "> Manual clinician review is required before any prescribing decision.",
        "",
    ]
    if evidence:
        lines.extend([
            "## Evidence Reviewed",
            "",
            "| # | Source | Finding |",
            "| --- | --- | --- |",
        ])
        for i, row in enumerate(evidence, 1):
            tool = _label_for_tool(row.get("tool", ""))
            result = (row.get("result") or "")[:200].replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {i} | {tool} | {result} |")
        lines.append("")
    lines.extend([
        "---",
        "*Consult a licensed clinician before acting on this assessment.*",
    ])
    return "\n".join(lines)
