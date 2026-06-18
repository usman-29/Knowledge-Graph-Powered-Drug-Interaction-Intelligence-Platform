# CLAUDE.md - Project Instructions

## 1. Project Identity & Mission

- **Project Name:** Autonomous Clinical Discharge & Care-Plan Orchestrator.
- **Mission:** A secure, "Medical-Grade" **Conversational Agent** for drug safety verification.
- **Key Focus:** Guardrails and safety layers for agentic workflows, Monitoring and observability tools for AI agents (detect hallucination, drift, misuse), Access control and permission frameworks for multi-agent systems, Audit trails and explainability tooling for regulated industries (finance, healthcare, legal), Red-teaming frameworks for testing agent robustness against adversarial inputs., Data Governance (Veea Layer), and Explainable AI (GraphRAG).

## 2. Professional Folder Structure

Maintain the following hierarchy for all code additions:

- `app/config/`: Infrastructure (llm.py, settings).
- `app/models/`: Data contracts (state.py for LangGraph, schemas.py for Pydantic).
- `app/agents/`: Logic nodes (orchestrator.py, graph.py).
- `app/tools/`: Action functions (medical_tools.py).
- `app/db/`: Database management (neo4j_manager.py, ingestion.py).
- `app/memory/`: Persistence (SqliteSaver checkpoints).

## 3. Security & Governance Rules (CRITICAL)

- **Veea Proxy:** All LLM traffic MUST route through `localhost:8080` via `app/config/llm.py`.
- **Strict Orchestration:** No query reaches the Medical Agent without passing the `orchestrator.py` intent classification (MEDICAL vs. BLOCK).
- **Tool Access:** Tools must be class-based and decorated with `@tool` from `langchain_core`.
- **Zero PII:** Never output or request real patient PII (Names, SSNs, DOBs). Use `[REDACTED]` or unique IDs only.

## 4. Technical Stack

- **Framework:** LangGraph, Langchain, FasrAPI (Stateful Agentic Workflows).
- **LLM:** HuggingFace (Llama-3-8B-Instruct) behind Veea Proxy.
- **Database:** Neo4j (Knowledge Graph for drug-drug interactions).
- **Standards:** RxNorm (RxCUI) mapping for drug normalization; openFDA for external verification.

## 5. Coding Standards

- **Naming:** Follow the project's specific naming (e.g., `get_llm()`, `graph.py`, `orchestrator.py`).
- **State Management:** Always use the `AgentState` TypedDict from `app/models/state.py`.
- **Modularity:** Ensure the `Neo4jManager` is used as a singleton to prevent connection leaks.
- **Type Checking:** All tool outputs and final agent responses should follow schemas in `app/models/schemas.py`.

## 6. Execution Patterns

- **Ingestion:** Run via `app/db/ingestion.py` or `run_ingestion.py` before querying.
- **Reasoning:** Use the "Three-Tier Security Stack":
  1. Veea (Proxy Filter)
  2. Orchestrator (Intent Check)
  3. Medical Logic (Execution)
