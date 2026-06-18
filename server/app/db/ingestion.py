"""Drug-drug interaction ingestion (Kaggle DDI dataset)."""
import pandas as pd

from app.db.neo4j import db_manager


class MedicalDataIngestor:
    """Loads drug-drug interaction CSVs into the Knowledge Graph."""

    @staticmethod
    def ingest_drug_interactions(csv_path: str) -> None:
        """Create :Drug nodes and bidirectional INTERACTS_WITH edges.

        Drug names are title-cased on the way in (via APOC) so downstream
        case-insensitive matching works without normalization on every query.
        """
        print(f"--- Starting drug-interaction ingestion: {csv_path} ---")
        df = pd.read_csv(csv_path)

        cypher = """
        UNWIND $rows AS row
        MERGE (d1:Drug {name: apoc.text.capitalizeAll(row.drug1)})
        MERGE (d2:Drug {name: apoc.text.capitalizeAll(row.drug2)})
        MERGE (d1)-[r:INTERACTS_WITH]->(d2)
        SET r.description = row.desc,
            r.source = 'Drug Interactions Kaggle Dataset'
        """
        rows = [
            {
                "drug1": str(r["Drug 1"]).strip(),
                "drug2": str(r["Drug 2"]).strip(),
                "desc": str(r["Interaction Description"]).strip(),
            }
            for _, r in df.iterrows()
        ]

        try:
            db_manager.execute_query(cypher, {"rows": rows})
            print(f"--- Successfully ingested {len(rows):,} interactions ---")
        except Exception as exc:
            print(f"--- Ingestion failed: {exc} ---")
