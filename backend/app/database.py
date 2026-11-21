"""Small SQLite persistence layer for research reports and retrieved observations."""
import json
import os
import sqlite3
from pathlib import Path
from typing import Any


def database_path() -> Path:
    configured = os.getenv("ORCA_DB_PATH")
    return Path(configured).expanduser() if configured else Path(__file__).resolve().parents[2] / "orca_x.sqlite3"


def connect() -> sqlite3.Connection:
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


def initialize() -> None:
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS research_sessions (
            session_id TEXT PRIMARY KEY,
            query TEXT NOT NULL,
            region TEXT NOT NULL,
            mode TEXT NOT NULL,
            status TEXT NOT NULL,
            data_status TEXT NOT NULL,
            result_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS observations (
            session_id TEXT NOT NULL REFERENCES research_sessions(session_id) ON DELETE CASCADE,
            date TEXT NOT NULL,
            sst_c REAL,
            sst_samples INTEGER NOT NULL,
            chlorophyll_mg_m3 REAL,
            chlorophyll_samples INTEGER NOT NULL,
            PRIMARY KEY (session_id, date)
        );
        CREATE INDEX IF NOT EXISTS idx_sessions_created ON research_sessions(created_at DESC);
        CREATE TABLE IF NOT EXISTS source_observation_cache (
            dataset_id TEXT NOT NULL,
            observation_date TEXT NOT NULL,
            source_version TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            refreshed_at TEXT NOT NULL,
            PRIMARY KEY (dataset_id, observation_date)
        );
        """)


def save_session(result: dict[str, Any]) -> None:
    with connect() as db:
        db.execute("""INSERT OR REPLACE INTO research_sessions
            (session_id, query, region, mode, status, data_status, result_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (result["session_id"], result["query"], result["report"]["region"], result["mode"],
             result["status"], result["data_status"], json.dumps(result), result["created_at"]))
        db.execute("DELETE FROM observations WHERE session_id = ?", (result["session_id"],))
        db.executemany("""INSERT INTO observations
            (session_id, date, sst_c, sst_samples, chlorophyll_mg_m3, chlorophyll_samples)
            VALUES (?, ?, ?, ?, ?, ?)""",
            [(result["session_id"], row["date"], row.get("sst_c"), row.get("sst_samples", 0),
              row.get("chlorophyll_mg_m3"), row.get("chlorophyll_samples", 0))
             for row in result.get("chart", {}).get("data", [])])


def get_session(session_id: str) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute("SELECT result_json FROM research_sessions WHERE session_id = ?", (session_id,)).fetchone()
    return json.loads(row["result_json"]) if row else None


def list_sessions() -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute("SELECT result_json FROM research_sessions ORDER BY created_at DESC").fetchall()
    return [json.loads(row["result_json"]) for row in rows]


def delete_session(session_id: str) -> bool:
    with connect() as db:
        cursor = db.execute("DELETE FROM research_sessions WHERE session_id = ?", (session_id,))
    return cursor.rowcount > 0


def get_source_cache(dataset_id: str, observation_date: str, source_version: str) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute("""SELECT payload_json FROM source_observation_cache
            WHERE dataset_id = ? AND observation_date = ? AND source_version = ?""",
            (dataset_id, observation_date, source_version)).fetchone()
    return json.loads(row["payload_json"]) if row else None


def save_source_cache(dataset_id: str, observation_date: str, source_version: str, payload: dict[str, Any]) -> None:
    from datetime import datetime, timezone
    with connect() as db:
        db.execute("""INSERT OR REPLACE INTO source_observation_cache
            (dataset_id, observation_date, source_version, payload_json, refreshed_at)
            VALUES (?, ?, ?, ?, ?)""",
            (dataset_id, observation_date, source_version, json.dumps(payload), datetime.now(timezone.utc).isoformat()))
