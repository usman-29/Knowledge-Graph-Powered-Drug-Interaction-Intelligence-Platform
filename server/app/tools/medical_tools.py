"""Clinical tools the Medical Agent is permitted to call.

These are the *only* functions allowed to touch external systems (Neo4j,
openFDA). Every tool returns plain strings — the Medical Agent records each
return value as an evidence row so the output guardrail can verify grounding
before the answer is released.
"""
import requests
from langchain_core.tools import tool

from app.config.settings import settings
from app.db.neo4j import db_manager


class MedicalTools:
    @tool
    def resolve_rxcui(drug_name: str) -> str:
        """Resolve a plain drug name to its RxNorm CUI via the Knowledge Graph.

        Always call this FIRST so downstream FDA lookups have a validated,
        standardized identifier instead of a free-form name.
        Returns either "RxCUI=… | Preferred name: …" or "NOT_FOUND — …".
        """
        cypher = """
        MATCH (d:Drug)-[:MAPS_TO]->(c:Concept)
        WHERE toUpper(d.name) = toUpper($name)
        RETURN c.rxcui AS rxcui, c.preferred_name AS preferred_name
        LIMIT 1
        """
        results = db_manager.execute_query(cypher, {"name": drug_name})
        if not results:
            return f"NOT_FOUND — {drug_name} has no RxNorm mapping in the Knowledge Graph."
        row = results[0]
        return f"RxCUI={row['rxcui']} | Preferred name: {row['preferred_name']}"

    @tool
    def check_local_interactions(drug_name: str) -> str:
        """List ALL known drug-drug interactions for a single drug from the
        Knowledge Graph. Each row preserves the edge direction so the agent
        can tell whether `drug_name` is the SUBJECT (perpetrator) or the
        PARTNER (victim) of the described mechanism.
        """
        cypher = """
        MATCH (d1:Drug)-[r:INTERACTS_WITH]->(d2:Drug)
        WHERE toUpper(d1.name) = toUpper($name)
           OR toUpper(d2.name) = toUpper($name)
        RETURN d1.name AS subject, d2.name AS partner, r.description AS description
        ORDER BY partner
        """
        results = db_manager.execute_query(cypher, {"name": drug_name})
        if not results:
            return f"No interactions recorded for {drug_name} in the Knowledge Graph."

        lines = [f"Knowledge Graph findings for {drug_name} ({len(results)} interactions):"]
        for res in results:
            lines.append(
                f"  - [{res['subject']} → {res['partner']}] {res['description']}"
            )
        lines.append(
            "(Direction notation: [SUBJECT → PARTNER] — the description's grammatical "
            "subject is the SUBJECT drug; do not invert this when summarising.)"
        )
        return "\n".join(lines)

    @tool
    def check_interaction_pair(drug_a: str, drug_b: str) -> str:
        """Check whether two specific drugs have a recorded interaction in the
        Knowledge Graph. Returns a directional fact: which drug is the SUBJECT
        of the described mechanism and which is the PARTNER.

        Use this for every (new_drug, existing_medication) pair when assessing
        whether a new prescription is safe to add to an existing regimen.
        """
        cypher = """
        MATCH (d1:Drug)-[r:INTERACTS_WITH]->(d2:Drug)
        WHERE (toUpper(d1.name) = toUpper($drug_a) AND toUpper(d2.name) = toUpper($drug_b))
           OR (toUpper(d1.name) = toUpper($drug_b) AND toUpper(d2.name) = toUpper($drug_a))
        RETURN d1.name AS subject, d2.name AS partner, r.description AS description
        LIMIT 1
        """
        results = db_manager.execute_query(
            cypher, {"drug_a": drug_a, "drug_b": drug_b}
        )
        if not results:
            return (
                f"No recorded interaction between {drug_a} and {drug_b} in the "
                "Knowledge Graph."
            )
        row = results[0]
        return (
            f"Interaction [{row['subject']} → {row['partner']}]: {row['description']}\n"
            f"DIRECTION: '{row['subject']}' is the grammatical subject of the "
            f"description; '{row['partner']}' is the partner drug. Do not invert "
            f"this when reporting the interaction."
        )

    @tool
    def get_fda_blackbox_warning(rxcui: str) -> str:
        """Retrieve the official FDA boxed warning for a drug by RxCUI.

        Call `resolve_rxcui` first to obtain the RxCUI. openFDA is the
        authoritative source of truth for clinical warnings.
        """
        url = (
            f"{settings.OPENFDA_API_URL}"
            f"?api_key={settings.OPENFDA_API_KEY}"
            f'&search=openfda.rxcui.exact:"{rxcui}"'
            "&limit=1"
        )
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                results = response.json().get("results", [])
                if results:
                    warning = results[0].get(
                        "boxed_warning",
                        results[0].get("warnings", ["No specific warning found"]),
                    )
                    return f"FDA boxed warning: {warning[0]}"
            return "No FDA boxed warning on file for this medication."
        except Exception as exc:
            return f"FDA lookup unavailable ({exc})."
