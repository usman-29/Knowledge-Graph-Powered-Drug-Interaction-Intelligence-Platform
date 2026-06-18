"""RxNorm normalization: map :Drug nodes to RxNorm CUIs.

Uses the official RXNCONSO.RRF file (pipe-separated). For every :Drug node
already in the graph, find an English RxNorm entry with the same string
representation, create a :Concept{rxcui} node, and link them with MAPS_TO.
"""
import pandas as pd

from app.db.neo4j import db_manager


RXNCONSO_COLUMNS = [
    "RXCUI", "LAT", "TS", "LUI", "STT", "SUI", "ISPREF", "RXAUI",
    "SAUI", "SCUI", "SDUI", "SAB", "TTY", "CODE", "STR", "SRL",
    "SUPPRESS", "CVF",
]
CHUNK_SIZE = 100_000


class RxNormNormalizer:
    def __init__(self, rrf_path: str) -> None:
        self.rrf_path = rrf_path

    def normalize_existing_drugs(self) -> None:
        print("--- Fetching unique drugs from Neo4j ---")
        existing = db_manager.execute_query("MATCH (d:Drug) RETURN d.name AS name")
        drug_names = {row["name"].upper() for row in existing}
        print(f"--- Looking up RxCUIs for {len(drug_names):,} drugs ---")

        reader = pd.read_csv(
            self.rrf_path,
            sep="|",
            names=RXNCONSO_COLUMNS,
            index_col=False,
            quoting=3,
            chunksize=CHUNK_SIZE,
            dtype={"RXCUI": str},
        )

        matched = 0
        for chunk in reader:
            filtered = chunk[
                (chunk["LAT"] == "ENG")
                & (chunk["SAB"] == "RXNORM")
                & (chunk["STR"].str.upper().isin(drug_names))
            ]
            if not filtered.empty:
                self._link_to_neo4j(filtered)
                matched += len(filtered)

        print(f"--- Normalization complete. Linked {matched:,} concepts. ---")

    def _link_to_neo4j(self, df: pd.DataFrame) -> None:
        cypher = """
        UNWIND $rows AS row
        MATCH (d:Drug)
        WHERE toUpper(d.name) = toUpper(row.str)
        MERGE (c:Concept {rxcui: row.rxcui})
        ON CREATE SET c.preferred_name = row.str, c.source = 'RxNorm'
        MERGE (d)-[:MAPS_TO]->(c)
        """
        rows = [{"rxcui": r["RXCUI"], "str": r["STR"]} for _, r in df.iterrows()]
        db_manager.execute_query(cypher, {"rows": rows})
