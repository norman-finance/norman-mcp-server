"""Encrypted durable subscription state for a single hosted MCP worker."""

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

from cryptography.fernet import Fernet


class SubscriptionStore:
    def __init__(self, path: str, key: str) -> None:
        if not Path(path).is_absolute():
            raise ValueError("Event subscription storage must use an absolute path")
        self.cipher = Fernet(key.encode())
        self.path = path
        parent = Path(path).parent
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Create the database with restrictive permissions before SQLite opens it.
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(descriptor)
        os.chmod(path, 0o600)
        with self.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS subscriptions (id TEXT PRIMARY KEY, payload BLOB NOT NULL)"
            )

        self.records()  # Fail startup if an existing database uses another encryption key.

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def get(self, identity: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT payload FROM subscriptions WHERE id = ?", (identity,)
            ).fetchone()
        return cast(dict[str, Any], json.loads(self.cipher.decrypt(row[0]))) if row else None

    def put(self, record: dict[str, Any]) -> None:
        payload = self.cipher.encrypt(json.dumps(record, separators=(",", ":")).encode())
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO subscriptions (id, payload) VALUES (?, ?)",
                (record["id"], payload),
            )

    def delete(self, identity: str) -> None:
        with self.connect() as db:
            db.execute("DELETE FROM subscriptions WHERE id = ?", (identity,))

    def records(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("SELECT payload FROM subscriptions").fetchall()
        return [json.loads(self.cipher.decrypt(row[0])) for row in rows]
