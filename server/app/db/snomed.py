"""
SNOMED CT RF2 Snapshot ingestor.

Two ingestion modes:

  ingest_drug_safety_subset()  [default, free-tier safe]
    Reads existing :Drug nodes from Neo4j, scans SNOMED descriptions for
    name matches, and only creates :SnomedConcept nodes for those matched
    drugs plus their immediate IS-A parent concepts.
    Footprint: ~hundreds of nodes instead of ~600K.

  ingest_all()  [requires Neo4j paid tier or AuraDB Unlimited]
    Full RF2 snapshot — all active concepts, FSN descriptions, and IS-A
    relationships (~600K nodes, several million edges).

RF2 file layout (tab-separated, UTF-8):

  sct2_Concept_Snapshot_*         id | effectiveTime | active | moduleId | definitionStatusId
  sct2_Description_Snapshot-en_*  id | effectiveTime | active | moduleId | conceptId
                                     | languageCode  | typeId | term     | caseSignificanceId
  sct2_Relationship_Snapshot_*    id | effectiveTime | active | moduleId | sourceId
                                     | destinationId | ...    | typeId   | ...
"""
from __future__ import annotations

import pandas as pd
from pathlib import Path

from app.db.neo4j import db_manager


FSN_TYPE_ID      = "900000000000003001"   # Fully Specified Name
SYNONYM_TYPE_ID  = "900000000000013009"   # Synonym
IS_A_TYPE_ID     = "116680003"           # IS-A attribute type
CHUNK_SIZE = 50_000


class SnomedIngestor:
    """Loads SNOMED CT RF2 snapshot data into the Knowledge Graph."""

    def __init__(self, snomed_dir: str | Path):
        self.dir = Path(snomed_dir)
        self.concept_file = self._find("sct2_Concept_Snapshot")
        self.description_file = self._find("sct2_Description_Snapshot")
        self.relationship_file = self._find("sct2_Relationship_Snapshot")

    def _find(self, prefix: str) -> Path:
        matches = list(self.dir.glob(f"{prefix}*.txt"))
        if not matches:
            raise FileNotFoundError(f"No file matching {prefix}*.txt in {self.dir}")
        return matches[0]

    # ── Public API ────────────────────────────────────────────────────────────

    def ingest_drug_safety_subset(self) -> None:
        """
        Targeted ingestion scoped to drugs already in the Knowledge Graph.

        Steps:
          1. Fetch drug names from :Drug nodes in Neo4j.
          2. Scan all active English SNOMED descriptions (synonyms + FSNs) and
             collect every concept whose term matches a drug name, keeping both
             the matched drug name and the concept's FSN.
          3. Create :SnomedConcept nodes only for matched concepts.
          4. Create (:Drug)-[:HAS_SNOMED_CODE]->(:SnomedConcept) edges.
          5. Scan the Relationship file for IS-A edges of matched concepts and
             create their immediate parent :SnomedConcept nodes (one hop up).
        """
        self._ensure_index()

        drug_names, upper_to_orig = self._fetch_drug_names()
        if not drug_names:
            print("--- No :Drug nodes found in Neo4j. Run drug-interaction ingestion first. ---")
            return

        print(f"--- Matching {len(drug_names):,} drug names against SNOMED descriptions ---")

        # hits: list of {sctid, fsn, drug_name}
        hits = self._match_descriptions(drug_names, upper_to_orig)
        if not hits:
            print("--- No SNOMED description matches found for existing drug names. ---")
            return

        print(f"--- Matched {len(hits):,} SNOMED concepts ---")
        self._upsert_concepts(hits)
        self._link_drugs_to_snomed(hits)
        self._ingest_isa_edges({h["sctid"] for h in hits})
        print("--- SNOMED drug-safety subset ingestion complete ---")

    def ingest_all(self) -> None:
        """Full RF2 ingestion. Requires a Neo4j tier with >200K node capacity."""
        self._ensure_index()
        self._ingest_all_concepts()
        self._ingest_all_descriptions()
        self._ingest_all_relationships()
        print("--- SNOMED full ingestion complete ---")

    # ── Subset helpers ────────────────────────────────────────────────────────

    def _fetch_drug_names(self) -> tuple[set[str], dict[str, str]]:
        """Returns (uppercased_names_set, upper→original mapping)."""
        rows = db_manager.execute_query("MATCH (d:Drug) RETURN d.name AS name")
        upper_to_orig = {r["name"].upper(): r["name"] for r in rows}
        return set(upper_to_orig.keys()), upper_to_orig

    def _match_descriptions(
        self, drug_names: set[str], upper_to_orig: dict[str, str]
    ) -> list[dict]:
        """
        Single-pass scan of all active English descriptions.

        Searches synonyms AND FSNs — FSNs include semantic tags like
        "(substance)" and would never match a plain drug name alone.

        Returns a list of {sctid, fsn, drug_name} dicts where drug_name
        is the original Neo4j :Drug name (title-cased) that triggered the hit.
        """
        columns = [
            "id", "effectiveTime", "active", "moduleId", "conceptId",
            "languageCode", "typeId", "term", "caseSignificanceId",
        ]
        reader = pd.read_csv(
            self.description_file,
            sep="\t",
            names=columns,
            header=0,
            dtype=str,
            chunksize=CHUNK_SIZE,
            keep_default_na=False,
            quoting=3,
        )

        sctid_to_drug: dict[str, str] = {}   # conceptId → original Neo4j drug name
        all_fsns: dict[str, str] = {}        # conceptId → FSN (buffered for all concepts)

        for chunk in reader:
            active_en = chunk[
                (chunk["active"] == "1") & (chunk["languageCode"] == "en")
            ]

            # Match synonyms + FSNs against the drug name set (case-insensitive)
            name_hits = active_en[
                active_en["typeId"].isin([FSN_TYPE_ID, SYNONYM_TYPE_ID])
                & active_en["term"].str.upper().isin(drug_names)
            ]
            for _, row in name_hits.iterrows():
                cid = row["conceptId"]
                if cid not in sctid_to_drug:
                    sctid_to_drug[cid] = upper_to_orig[row["term"].upper()]

            # Buffer FSNs for every concept (filter to matched ones at the end)
            fsn_hits = active_en[active_en["typeId"] == FSN_TYPE_ID]
            # Use pandas vectorised assignment for speed on large chunks
            for cid, fsn in zip(fsn_hits["conceptId"], fsn_hits["term"]):
                all_fsns[cid] = fsn

        return [
            {
                "sctid": cid,
                "fsn": all_fsns.get(cid, "(no FSN)"),
                "drug_name": sctid_to_drug[cid],
            }
            for cid in sctid_to_drug
        ]

    def _upsert_concepts(self, hits: list[dict]) -> None:
        rows = [{"sctid": h["sctid"], "fsn": h["fsn"]} for h in hits]
        db_manager.execute_query(
            "UNWIND $rows AS row "
            "MERGE (c:SnomedConcept {sctid: row.sctid}) "
            "SET c.fsn = row.fsn, c.active = true, c.source = 'SNOMED-CT'",
            {"rows": rows},
        )
        print(f"--- Upserted {len(rows):,} :SnomedConcept nodes ---")

    def _link_drugs_to_snomed(self, hits: list[dict]) -> None:
        """Create (:Drug)-[:HAS_SNOMED_CODE]->(:SnomedConcept) edges."""
        rows = [{"drug_name": h["drug_name"], "sctid": h["sctid"]} for h in hits]
        db_manager.execute_query(
            "UNWIND $rows AS row "
            "MATCH (d:Drug) WHERE toUpper(d.name) = toUpper(row.drug_name) "
            "MATCH (c:SnomedConcept {sctid: row.sctid}) "
            "MERGE (d)-[:HAS_SNOMED_CODE]->(c)",
            {"rows": rows},
        )
        print(f"--- Created :HAS_SNOMED_CODE edges ---")

    def _ingest_isa_edges(self, source_ids: set[str]) -> None:
        """
        Ingest IS-A relationships for matched concepts plus create parent nodes.

        We only ingest one hop upward — enough to place each drug concept in its
        immediate class (e.g., "Analgesic", "Anticoagulant") without pulling in
        the entire ontology hierarchy.
        """
        print("--- Scanning IS-A relationships for matched concepts ---")
        columns = [
            "id", "effectiveTime", "active", "moduleId", "sourceId",
            "destinationId", "relationshipGroup", "typeId",
            "characteristicTypeId", "modifierId",
        ]
        reader = pd.read_csv(
            self.relationship_file,
            sep="\t",
            names=columns,
            header=0,
            dtype=str,
            chunksize=CHUNK_SIZE,
            keep_default_na=False,
            quoting=3,
        )
        edges: list[dict] = []
        parent_ids: set[str] = set()
        for chunk in reader:
            hits = chunk[
                (chunk["active"] == "1")
                & (chunk["typeId"] == IS_A_TYPE_ID)
                & (chunk["sourceId"].isin(source_ids))
            ]
            for _, row in hits.iterrows():
                edges.append({"src": row["sourceId"], "dst": row["destinationId"]})
                parent_ids.add(row["destinationId"])

        if not edges:
            print("--- No IS-A edges found for matched concepts ---")
            return

        # Ensure parent nodes exist (sctid only; FSN will be blank unless
        # they happen to also be drug names already matched above).
        parent_rows = [{"sctid": pid} for pid in parent_ids - source_ids]
        if parent_rows:
            db_manager.execute_query(
                "UNWIND $rows AS row "
                "MERGE (c:SnomedConcept {sctid: row.sctid}) "
                "SET c.source = 'SNOMED-CT'",
                {"rows": parent_rows},
            )

        # Resolve parent FSNs from the Description file so parents are labelled.
        self._attach_fsns_for(parent_ids - source_ids)

        db_manager.execute_query(
            "UNWIND $rows AS row "
            "MATCH (child:SnomedConcept {sctid: row.src}) "
            "MATCH (parent:SnomedConcept {sctid: row.dst}) "
            "MERGE (child)-[:IS_A]->(parent)",
            {"rows": edges},
        )
        print(f"--- Ingested {len(edges):,} IS-A edges, {len(parent_ids):,} parent nodes ---")

    def _attach_fsns_for(self, sctids: set[str]) -> None:
        """Set c.fsn on parent nodes by scanning the Description file for their IDs."""
        if not sctids:
            return
        columns = [
            "id", "effectiveTime", "active", "moduleId", "conceptId",
            "languageCode", "typeId", "term", "caseSignificanceId",
        ]
        reader = pd.read_csv(
            self.description_file,
            sep="\t",
            names=columns,
            header=0,
            dtype=str,
            chunksize=CHUNK_SIZE,
            keep_default_na=False,
            quoting=3,
        )
        rows: list[dict] = []
        for chunk in reader:
            hits = chunk[
                (chunk["active"] == "1")
                & (chunk["typeId"] == FSN_TYPE_ID)
                & (chunk["languageCode"] == "en")
                & (chunk["conceptId"].isin(sctids))
            ]
            for _, row in hits.iterrows():
                rows.append({"sctid": row["conceptId"], "fsn": row["term"]})

        if rows:
            db_manager.execute_query(
                "UNWIND $rows AS row "
                "MATCH (c:SnomedConcept {sctid: row.sctid}) SET c.fsn = row.fsn",
                {"rows": rows},
            )

    # ── Full-ingestion helpers ────────────────────────────────────────────────

    def _ensure_index(self) -> None:
        db_manager.execute_query(
            "CREATE CONSTRAINT snomed_sctid_unique IF NOT EXISTS "
            "FOR (c:SnomedConcept) REQUIRE c.sctid IS UNIQUE"
        )
        print("--- SNOMED indexes ensured ---")

    def _ingest_all_concepts(self) -> None:
        print(f"--- [Full] Ingesting concepts from {self.concept_file.name} ---")
        cypher = (
            "UNWIND $rows AS row "
            "MERGE (c:SnomedConcept {sctid: row.sctid}) "
            "SET c.active = true, c.source = 'SNOMED-CT'"
        )
        total = self._stream(
            self.concept_file,
            columns=["id", "effectiveTime", "active", "moduleId", "definitionStatusId"],
            filter_fn=lambda df: df[df["active"] == "1"],
            row_builder=lambda r: {"sctid": r["id"]},
            cypher=cypher,
            label="concepts",
        )
        print(f"--- Concepts ingested: {total:,} ---")

    def _ingest_all_descriptions(self) -> None:
        print(f"--- [Full] Ingesting FSN descriptions ---")
        cypher = (
            "UNWIND $rows AS row "
            "MATCH (c:SnomedConcept {sctid: row.sctid}) SET c.fsn = row.term"
        )
        total = self._stream(
            self.description_file,
            columns=[
                "id", "effectiveTime", "active", "moduleId", "conceptId",
                "languageCode", "typeId", "term", "caseSignificanceId",
            ],
            filter_fn=lambda df: df[
                (df["active"] == "1")
                & (df["typeId"] == FSN_TYPE_ID)
                & (df["languageCode"] == "en")
            ],
            row_builder=lambda r: {"sctid": r["conceptId"], "term": r["term"]},
            cypher=cypher,
            label="FSN descriptions",
        )
        print(f"--- FSN descriptions ingested: {total:,} ---")

    def _ingest_all_relationships(self) -> None:
        print(f"--- [Full] Ingesting IS-A relationships ---")
        cypher = (
            "UNWIND $rows AS row "
            "MATCH (child:SnomedConcept {sctid: row.src}) "
            "MATCH (parent:SnomedConcept {sctid: row.dst}) "
            "MERGE (child)-[:IS_A]->(parent)"
        )
        total = self._stream(
            self.relationship_file,
            columns=[
                "id", "effectiveTime", "active", "moduleId", "sourceId",
                "destinationId", "relationshipGroup", "typeId",
                "characteristicTypeId", "modifierId",
            ],
            filter_fn=lambda df: df[
                (df["active"] == "1") & (df["typeId"] == IS_A_TYPE_ID)
            ],
            row_builder=lambda r: {"src": r["sourceId"], "dst": r["destinationId"]},
            cypher=cypher,
            label="IS-A edges",
        )
        print(f"--- IS-A edges ingested: {total:,} ---")

    def _stream(
        self,
        path: Path,
        columns: list[str],
        filter_fn,
        row_builder,
        cypher: str,
        label: str,
    ) -> int:
        """Chunked read → filter → build rows → UNWIND into Neo4j."""
        reader = pd.read_csv(
            path,
            sep="\t",
            names=columns,
            header=0,
            dtype=str,
            chunksize=CHUNK_SIZE,
            keep_default_na=False,
            quoting=3,
        )
        total = 0
        for i, chunk in enumerate(reader, start=1):
            filtered = filter_fn(chunk)
            if filtered.empty:
                continue
            rows = [row_builder(r) for _, r in filtered.iterrows()]
            db_manager.execute_query(cypher, {"rows": rows})
            total += len(rows)
            if i % 10 == 0:
                print(f"    {label}: {total:,} rows so far…")
        return total
