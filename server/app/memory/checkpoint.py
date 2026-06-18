"""SqliteSaver factory.

LangGraph's SqliteSaver persists per-thread conversation state so turns are
replayable for audit. We open a single module-level connection with
check_same_thread=False so FastAPI's threadpool can share it safely.
"""
import sqlite3
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

from app.config.settings import settings

_DB_PATH = Path(settings.CHECKPOINT_DB)
_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# Module-level connection — one per process, shared across threads.
_conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
_checkpointer = SqliteSaver(_conn)


def get_checkpointer() -> SqliteSaver:
    return _checkpointer
