"""SQLite storage in one local file (data/socklock.db). Plain SQL, no ORM."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS generations (
    id            TEXT PRIMARY KEY,   -- SLM-20261109-K7QX
    created_at    TEXT NOT NULL,
    backend       TEXT NOT NULL,      -- cli / api / mock
    model         TEXT NOT NULL,      -- model we asked for ('mock' in mock mode)
    served_model  TEXT,               -- model that actually answered
    effort        TEXT,
    elements      TEXT NOT NULL,      -- JSON list, e.g. ["hook", "first_lines"]
    n_variants    INTEGER NOT NULL,
    context       TEXT,               -- JSON: product / audience / angle
    input_script  TEXT NOT NULL,      -- JSON of the winning script we started from
    usage         TEXT                -- JSON: token counts
);
CREATE TABLE IF NOT EXISTS variants (
    id            TEXT PRIMARY KEY,   -- SLM-20261109-K7QX-v1 (goes into the Meta ad name)
    generation_id TEXT NOT NULL REFERENCES generations(id),
    n             INTEGER NOT NULL,
    angle         TEXT,
    script        TEXT NOT NULL,      -- JSON of the full variant script
    accepted_at   TEXT                -- NULL until a designer marks it as used
);
CREATE TABLE IF NOT EXISTS time_logs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    generation_id TEXT NOT NULL REFERENCES generations(id),
    minutes       REAL NOT NULL,
    logged_at     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ad_results (   -- last imported Meta export (each import replaces it)
    ad_name         TEXT PRIMARY KEY,
    variant_id      TEXT,               -- NULL = control ad
    spend           REAL, impressions REAL, clicks REAL, purchases REAL, value REAL,
    value_estimated INTEGER,            -- 1 = value = purchases x LTV
    source_file     TEXT,
    imported_at     TEXT
);
"""


def now():
    return datetime.now().isoformat(timespec="seconds")


@contextmanager
def open_db(db_path):
    """Open the database, create tables if needed, commit at the end, always close."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10)  # a new connection per call -> safe with web threads
    conn.row_factory = sqlite3.Row  # rows behave like dicts: row["id"]
    conn.executescript(SCHEMA)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def generation_exists(db_path, generation_id):
    with open_db(db_path) as conn:
        row = conn.execute("SELECT 1 FROM generations WHERE id = ?", (generation_id,)).fetchone()
    return row is not None


def save_generation(db_path, generation):
    """Save one generate run and all its variants (dict built by generator.generate)."""
    g = generation
    with open_db(db_path) as conn:
        conn.execute(
            "INSERT INTO generations (id, created_at, backend, model, served_model, effort, elements,"
            " n_variants, context, input_script, usage) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (g["id"], g["created_at"], g["backend"], g["model"], g["served_model"], g["effort"],
             json.dumps(g["elements"]), len(g["variants"]), json.dumps(g["context"]),
             json.dumps(g["input_script"]), json.dumps(g["usage"])),
        )
        for v in g["variants"]:
            conn.execute(
                "INSERT INTO variants (id, generation_id, n, angle, script) VALUES (?, ?, ?, ?, ?)",
                (v["id"], g["id"], v["n"], v["angle"], json.dumps(v["script"])),
            )


def get_variant(db_path, variant_id):
    with open_db(db_path) as conn:
        row = conn.execute("SELECT * FROM variants WHERE id = ?", (variant_id,)).fetchone()
    if row is None:
        return None
    variant = dict(row)
    variant["script"] = json.loads(variant["script"])
    return variant


def accept_variants(db_path, variant_ids):
    """Mark variants as used by a designer. Returns (accepted ids, unknown ids)."""
    accepted, unknown = [], []
    with open_db(db_path) as conn:
        for variant_id in variant_ids:
            row = conn.execute("SELECT accepted_at FROM variants WHERE id = ?", (variant_id,)).fetchone()
            if row is None:
                unknown.append(variant_id)
                continue
            if row["accepted_at"] is None:  # accepting twice keeps the first timestamp
                conn.execute("UPDATE variants SET accepted_at = ? WHERE id = ?", (now(), variant_id))
            accepted.append(variant_id)
    return accepted, unknown


def log_time(db_path, generation_id, minutes):
    if minutes <= 0:
        raise ValueError("Кількість хвилин має бути більшою за 0.")
    if not generation_exists(db_path, generation_id):
        raise ValueError(f"Генерацію {generation_id} не знайдено.")
    with open_db(db_path) as conn:
        conn.execute("INSERT INTO time_logs (generation_id, minutes, logged_at) VALUES (?, ?, ?)",
                     (generation_id, minutes, now()))


def replace_ad_results(db_path, ads, value_estimated, source_file):
    """Store the latest Meta export. Ads Manager exports are cumulative, so we replace the old one."""
    with open_db(db_path) as conn:
        conn.execute("DELETE FROM ad_results")
        for ad in ads:
            conn.execute(
                "INSERT INTO ad_results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (ad["ad_name"], ad["variant_id"], ad["spend"], ad["impressions"], ad["clicks"],
                 ad["purchases"], ad["value"], int(value_estimated), str(source_file), now()),
            )


def load_ad_results(db_path):
    with open_db(db_path) as conn:
        rows = conn.execute("SELECT * FROM ad_results ORDER BY ad_name").fetchall()
    return [dict(row) for row in rows]


def pilot_stats(db_path):
    """Raw numbers for the report: variants generated/accepted (total and per model), minutes."""
    with open_db(db_path) as conn:
        per_model = conn.execute(
            "SELECT g.model, COUNT(v.id) AS generated, COUNT(v.accepted_at) AS accepted"
            " FROM variants v JOIN generations g ON g.id = v.generation_id"
            " GROUP BY g.model ORDER BY g.model"
        ).fetchall()
        minutes = [row["minutes"] for row in conn.execute("SELECT minutes FROM time_logs")]
        mock_generations = conn.execute(
            "SELECT COUNT(*) FROM generations WHERE backend = 'mock'").fetchone()[0]
    per_model = [dict(row) for row in per_model]
    return {
        "generated": sum(row["generated"] for row in per_model),
        "accepted": sum(row["accepted"] for row in per_model),
        "per_model": per_model,
        "minutes": minutes,
        "mock_generations": mock_generations,
    }
