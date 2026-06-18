"""Singleton Neo4j driver wrapper.

`db_manager` is module-level so the application reuses one driver across
requests — Neo4j drivers maintain a connection pool internally, so creating
new ones per request leaks sockets.
"""
from neo4j import GraphDatabase

from app.config.settings import settings


class Neo4jManager:
    def __init__(self) -> None:
        self.uri = settings.NEO4J_URI
        self.user = settings.NEO4J_USER
        self.password = settings.NEO4J_PASSWORD
        self.database = settings.NEO4J_DATABASE
        self.driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))

    def execute_query(self, cypher: str, params: dict | None = None) -> list[dict]:
        """Run a Cypher statement and return records as a list of dicts."""
        with self.driver.session(database=self.database) as session:
            result = session.run(cypher, params or {})
            return [record.data() for record in result]

    def close(self) -> None:
        self.driver.close()


db_manager = Neo4jManager()
