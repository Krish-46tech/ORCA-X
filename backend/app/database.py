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
        CREATE TABLE IF NOT EXISTS retrieval_log (
            retrieval_id INTEGER PRIMARY KEY AUTOINCREMENT,
            dataset_id TEXT NOT NULL, status TEXT NOT NULL, started_at TEXT NOT NULL,
            finished_at TEXT, region TEXT, date_start TEXT, date_end TEXT,
            records INTEGER NOT NULL DEFAULT 0, cache_hit INTEGER NOT NULL DEFAULT 0,
            error TEXT, provenance_json TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_retrieval_log_started ON retrieval_log(started_at DESC);
        CREATE TABLE IF NOT EXISTS normalized_marine_observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL REFERENCES research_sessions(session_id) ON DELETE CASCADE,
            dataset_id TEXT NOT NULL, standardized_variable TEXT NOT NULL,
            observation_time TEXT, record_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_marine_obs_session ON normalized_marine_observations(session_id, observation_time);
        """)


def cache_inventory() -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute("""SELECT dataset_id, COUNT(*) AS records,
            MIN(observation_date) AS date_start, MAX(observation_date) AS date_end,
            MAX(refreshed_at) AS last_refreshed,
            SUM(length(payload_json)) AS bytes FROM source_observation_cache GROUP BY dataset_id""").fetchall()
    return [dict(row) for row in rows]


def delete_dataset_cache(dataset_id: str) -> int:
    with connect() as db:
        cursor = db.execute("DELETE FROM source_observation_cache WHERE dataset_id = ?", (dataset_id,))
    return cursor.rowcount


def log_retrieval(dataset_id: str, status: str, started_at: str, *, finished_at: str | None = None,
                  region: str | None = None, date_start: str | None = None, date_end: str | None = None,
                  records: int = 0, cache_hit: bool = False, error: str | None = None,
                  provenance: dict | None = None) -> None:
    with connect() as db:
        db.execute("""INSERT INTO retrieval_log
            (dataset_id,status,started_at,finished_at,region,date_start,date_end,records,cache_hit,error,provenance_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (dataset_id,status,started_at,finished_at,region,date_start,date_end,
              records,int(cache_hit),error,json.dumps(provenance or {})))


def list_retrievals(limit: int = 200) -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute("SELECT * FROM retrieval_log ORDER BY retrieval_id DESC LIMIT ?", (min(max(limit,1),500),)).fetchall()
    result = [dict(row) for row in rows]
    for row in result:
        row["provenance"] = json.loads(row.pop("provenance_json") or "{}")
    return result


def log_source_retrieval(dataset_id: str, status: str, *, region: str | None = None,
                         date_start: str | None = None, date_end: str | None = None,
                         records: int = 0, error: str | None = None, provenance: dict | None = None) -> None:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    log_retrieval(dataset_id, status, now, finished_at=now, region=region, date_start=date_start,
                  date_end=date_end, records=records, error=error, provenance=provenance)


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
        db.execute("DELETE FROM normalized_marine_observations WHERE session_id = ?", (result["session_id"],))
        db.executemany("""INSERT INTO normalized_marine_observations
            (session_id,dataset_id,standardized_variable,observation_time,record_json) VALUES (?,?,?,?,?)""",
            [(result["session_id"], row["dataset_id"], row["standardized_variable"], row.get("observation_time"), json.dumps(row))
             for row in result.get("normalized_observations", [])])


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
