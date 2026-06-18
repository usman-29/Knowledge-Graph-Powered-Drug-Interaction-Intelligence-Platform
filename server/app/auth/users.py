"""
User store — single SQLite table (`users`) for the entire system.

The frontend has no database. All user state (credentials, role, profile)
lives here. Auth.js on the frontend calls POST /auth/verify to authenticate;
new accounts are created via POST /auth/register.

Schema:
  id            TEXT PRIMARY KEY  (UUID)
  email         TEXT UNIQUE       (login identifier, lowercased)
  name          TEXT              (display name)
  password_hash TEXT              (bcrypt with cost 12)
  role          TEXT              (ADMIN / CLINICIAN / PATIENT / GUEST)
  created_at    INTEGER           (unix seconds)
  updated_at    INTEGER
"""
from __future__ import annotations

import sqlite3
import time
import uuid
from pathlib import Path

import bcrypt

from app.config.settings import settings
from app.models.schemas import Role


_db_path = Path(settings.USERS_DB)
_db_path.parent.mkdir(parents=True, exist_ok=True)

# Single module-level connection shared across FastAPI's threadpool.
_conn = sqlite3.connect(str(_db_path), check_same_thread=False)
_conn.row_factory = sqlite3.Row
_conn.execute(
    """
    CREATE TABLE IF NOT EXISTS users (
        id            TEXT PRIMARY KEY,
        email         TEXT UNIQUE NOT NULL,
        name          TEXT,
        password_hash TEXT NOT NULL,
        role          TEXT NOT NULL CHECK(role IN ('ADMIN','CLINICIAN','PATIENT','GUEST')),
        created_at    INTEGER NOT NULL,
        updated_at    INTEGER NOT NULL
    )
    """
)
_conn.commit()


# ── Row helpers ───────────────────────────────────────────────────────────────


def _row_to_public(row: sqlite3.Row) -> dict:
    """Public-safe user dict — never includes password_hash."""
    return {
        "id": row["id"],
        "email": row["email"],
        "name": row["name"],
        "role": row["role"],
        "created_at": row["created_at"],
    }


# ── Public API ────────────────────────────────────────────────────────────────


class EmailAlreadyExists(Exception):
    pass


def create_user(*, email: str, name: str, password: str, role: Role) -> dict:
    """Create a new account. Raises EmailAlreadyExists on duplicate."""
    email = email.strip().lower()
    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")
    user_id = str(uuid.uuid4())
    now = int(time.time())

    try:
        _conn.execute(
            """
            INSERT INTO users (id, email, name, password_hash, role, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, email, name, password_hash, role.value, now, now),
        )
        _conn.commit()
    except sqlite3.IntegrityError as exc:
        if "UNIQUE" in str(exc):
            raise EmailAlreadyExists(email) from exc
        raise

    return {"id": user_id, "email": email, "name": name, "role": role.value, "created_at": now}


def verify_credentials(email: str, password: str) -> dict | None:
    """Look up by email + check bcrypt. Returns the public user dict on success,
    None on any failure (wrong email OR wrong password — never disclose which)."""
    email = email.strip().lower()
    row = _conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if row is None:
        return None
    if not bcrypt.checkpw(password.encode("utf-8"), row["password_hash"].encode("utf-8")):
        return None
    return _row_to_public(row)


def get_role(user_id: str) -> Role:
    """Used by access_control_node — defaults to GUEST for unknown ids."""
    row = _conn.execute("SELECT role FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        return Role.GUEST
    try:
        return Role(row["role"])
    except ValueError:
        return Role.GUEST


def set_role(user_id: str, role: Role) -> None:
    """Admin-only role change (used by POST /admin/users for non-account users
    like the legacy `admin` seed and the `anonymous` placeholder)."""
    now = int(time.time())
    _conn.execute(
        """
        INSERT INTO users (id, email, name, password_hash, role, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET role = excluded.role, updated_at = excluded.updated_at
        """,
        (user_id, f"{user_id}@placeholder.local", user_id, "", role.value, now, now),
    )
    _conn.commit()


def list_users() -> list[dict]:
    rows = _conn.execute(
        "SELECT id, email, name, role, created_at FROM users ORDER BY created_at DESC"
    ).fetchall()
    return [
        {
            "id": r["id"],
            "email": r["email"],
            "name": r["name"],
            "role": r["role"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]


def find_user_by_id(user_id: str) -> dict | None:
    row = _conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return _row_to_public(row) if row else None


# ── Seed defaults ─────────────────────────────────────────────────────────────


def _seed_defaults() -> None:
    """Built-in `admin` and `anonymous` rows for the first-run case. Use
    INSERT OR IGNORE so subsequent boots don't clobber real accounts."""
    now = int(time.time())
    _conn.executemany(
        """
        INSERT OR IGNORE INTO users (id, email, name, password_hash, role, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ("admin", "admin@placeholder.local", "admin", "", "ADMIN", now, now),
            ("anonymous", "anonymous@placeholder.local", "anonymous", "", "GUEST", now, now),
        ],
    )
    _conn.commit()


_seed_defaults()
