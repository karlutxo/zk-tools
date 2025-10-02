"""Utilities for SQLite persistence."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from flask import current_app, g
from werkzeug.security import check_password_hash, generate_password_hash

DB_PATH = Path(__file__).resolve().parent / "zk_tools.sqlite3"


def get_connection() -> sqlite3.Connection:
    """Return a SQLite connection stored in the application context."""
    if "_db_conn" not in g:
        g._db_conn = sqlite3.connect(DB_PATH)
        g._db_conn.row_factory = sqlite3.Row
    return g._db_conn  # type: ignore[return-value]


def close_connection(_: Optional[BaseException] = None) -> None:
    connection: Optional[sqlite3.Connection] = g.pop("_db_conn", None)
    if connection is not None:
        connection.close()


def init_db() -> None:
    connection = get_connection()
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_admin INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    connection.commit()


def init_app(app) -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    app.teardown_appcontext(close_connection)

    with app.app_context():
        init_db()
        ensure_default_admin()


def _row_to_user(row: sqlite3.Row) -> Dict[str, object]:
    return {
        "id": row["id"],
        "username": row["username"],
        "is_admin": bool(row["is_admin"]),
        "created_at": row["created_at"],
    }


def list_users() -> List[Dict[str, object]]:
    connection = get_connection()
    rows = connection.execute(
        "SELECT id, username, is_admin, created_at FROM users ORDER BY username COLLATE NOCASE"
    ).fetchall()
    return [_row_to_user(row) for row in rows]


def get_user_by_id(user_id: int) -> Optional[Dict[str, object]]:
    connection = get_connection()
    row = connection.execute(
        "SELECT id, username, is_admin, created_at FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    if row is None:
        return None
    return _row_to_user(row)


def get_user_by_username(username: str) -> Optional[Dict[str, object]]:
    connection = get_connection()
    row = connection.execute(
        "SELECT id, username, password_hash, is_admin, created_at FROM users WHERE username = ?",
        (username,),
    ).fetchone()
    if row is None:
        return None
    user = _row_to_user(row)
    user["password_hash"] = row["password_hash"]
    return user


def authenticate_user(username: str, password: str) -> Optional[Dict[str, object]]:
    user = get_user_by_username(username)
    if not user:
        return None
    password_hash = user.pop("password_hash", None)
    if not password_hash or not check_password_hash(password_hash, password):
        return None
    return user


def create_user(username: str, password: str, is_admin: bool = False) -> Dict[str, object]:
    connection = get_connection()
    try:
        connection.execute(
            "INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, ?)",
            (username.strip(), generate_password_hash(password), int(is_admin)),
        )
    except sqlite3.IntegrityError as exc:
        raise ValueError("El nombre de usuario ya existe.") from exc
    connection.commit()
    created = get_user_by_username(username)
    if not created:
        raise RuntimeError("No se pudo crear el usuario.")
    created.pop("password_hash", None)
    return created


def update_user(
    user_id: int,
    *,
    password: Optional[str] = None,
    is_admin: Optional[bool] = None,
) -> Dict[str, object]:
    connection = get_connection()
    if password is not None and password:
        connection.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (generate_password_hash(password), user_id),
        )
    if is_admin is not None:
        _ensure_admin_integrity(user_id, is_admin)
        connection.execute(
            "UPDATE users SET is_admin = ? WHERE id = ?",
            (int(is_admin), user_id),
        )
    connection.commit()
    updated = get_user_by_id(user_id)
    if not updated:
        raise ValueError("Usuario no encontrado")
    return updated


def delete_user(user_id: int) -> None:
    _ensure_admin_integrity(user_id, removing=True)
    connection = get_connection()
    connection.execute("DELETE FROM users WHERE id = ?", (user_id,))
    connection.commit()


def _ensure_admin_integrity(user_id: int, is_admin: Optional[bool] = None, removing: bool = False) -> None:
    connection = get_connection()
    row = connection.execute(
        "SELECT is_admin FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    if row is None:
        raise ValueError("Usuario no encontrado")
    was_admin = bool(row["is_admin"])
    will_be_admin = was_admin if is_admin is None else is_admin
    if removing:
        will_be_admin = False

    if was_admin and not will_be_admin:
        admin_count = connection.execute(
            "SELECT COUNT(*) FROM users WHERE is_admin = 1 AND id != ?",
            (user_id,),
        ).fetchone()[0]
        if admin_count == 0:
            raise ValueError("Debe existir al menos un usuario administrador.")


def ensure_default_admin() -> None:
    connection = get_connection()
    row = connection.execute("SELECT COUNT(*) FROM users").fetchone()
    if row and row[0] == 0:
        create_user("admin", "admin123", True)


def count_users() -> int:
    connection = get_connection()
    return connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]

