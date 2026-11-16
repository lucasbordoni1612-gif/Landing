"""SQLite storage: programs, applications, credits, usage, processed e-mails and
an append-only audit log.

Duplicate protection lives in the schema itself: a partial UNIQUE index allows
only one *active* application per program, and processed e-mails are keyed by
Message-ID.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any, Iterator

from .util import canonical_url, utcnow_iso

ACTIVE_APP_STATUSES = (
    "draft", "awaiting_approval", "approved", "submitting",
    "awaiting_manual_submission", "submitted", "accepted",
)
TERMINAL_APP_STATUSES = ("rejected", "rejected_by_user", "withdrawn", "superseded")

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS programs (
    id INTEGER PRIMARY KEY,
    key TEXT NOT NULL UNIQUE,
    provider TEXT NOT NULL,
    name TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'other',
    official_url TEXT NOT NULL,
    canonical_url TEXT NOT NULL UNIQUE,
    official_domains_json TEXT NOT NULL DEFAULT '[]',
    source TEXT NOT NULL DEFAULT 'seed',
    status TEXT NOT NULL DEFAULT 'unverified',
    details_json TEXT,
    details_hash TEXT,
    content_hash TEXT,
    evidence_check TEXT,
    fail_count INTEGER NOT NULL DEFAULT 0,
    eligibility_json TEXT,
    eligibility_overall TEXT,
    eligibility_at TEXT,
    first_seen_at TEXT NOT NULL,
    last_checked_at TEXT,
    last_verified_at TEXT,
    last_changed_at TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS program_snapshots (
    id INTEGER PRIMARY KEY,
    program_id INTEGER NOT NULL REFERENCES programs(id),
    fetched_at TEXT NOT NULL,
    url TEXT NOT NULL,
    content_hash TEXT,
    details_json TEXT NOT NULL,
    changes_json TEXT
);

CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY,
    program_id INTEGER NOT NULL REFERENCES programs(id),
    status TEXT NOT NULL,
    packet_json TEXT NOT NULL,
    packet_hash TEXT NOT NULL,
    profile_hash TEXT NOT NULL,
    program_details_hash TEXT,
    missing_json TEXT NOT NULL DEFAULT '[]',
    eligibility_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    approved_at TEXT,
    approved_by TEXT,
    approved_packet_hash TEXT,
    submitted_at TEXT,
    submission_method TEXT,
    submission_ref TEXT,
    decision_at TEXT,
    notes TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS one_active_application_per_program
    ON applications(program_id)
    WHERE status IN ({", ".join(repr(s) for s in ACTIVE_APP_STATUSES)});

CREATE TABLE IF NOT EXISTS credits (
    id INTEGER PRIMARY KEY,
    program_id INTEGER REFERENCES programs(id),
    application_id INTEGER REFERENCES applications(id),
    provider TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    amount REAL NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD',
    granted_at TEXT,
    expires_at TEXT,
    source TEXT NOT NULL,
    evidence TEXT,
    email_message_id TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (email_message_id, amount, currency, description)
);

CREATE TABLE IF NOT EXISTS credit_usage (
    id INTEGER PRIMARY KEY,
    credit_id INTEGER NOT NULL REFERENCES credits(id),
    used_at TEXT NOT NULL,
    amount REAL NOT NULL CHECK (amount > 0),
    note TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS emails_processed (
    message_id TEXT PRIMARY KEY,
    received_at TEXT,
    from_addr TEXT,
    subject TEXT,
    authenticated INTEGER NOT NULL,
    program_id INTEGER REFERENCES programs(id),
    application_id INTEGER REFERENCES applications(id),
    classification_json TEXT,
    action TEXT NOT NULL,
    processed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    at TEXT NOT NULL,
    kind TEXT NOT NULL,
    entity TEXT,
    entity_id INTEGER,
    detail_json TEXT
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


class DuplicateApplication(Exception):
    pass


def loads(value: str | None, default: Any = None) -> Any:
    if not value:
        return default
    return json.loads(value)


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


class Database:
    def __init__(self, path: str | Path):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        if str(path) != ":memory:":
            self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self.conn
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise

    def q(self, sql: str, params: tuple | dict = ()) -> list[sqlite3.Row]:
        return list(self.conn.execute(sql, params))

    def q1(self, sql: str, params: tuple | dict = ()) -> sqlite3.Row | None:
        return self.conn.execute(sql, params).fetchone()

    # --- audit log / meta ----------------------------------------------------

    def log(self, kind: str, entity: str | None = None, entity_id: int | None = None, **detail: Any) -> None:
        self.conn.execute(
            "INSERT INTO events (at, kind, entity, entity_id, detail_json) VALUES (?, ?, ?, ?, ?)",
            (utcnow_iso(), kind, entity, entity_id, dumps(detail) if detail else None),
        )

    def get_meta(self, key: str, default: str | None = None) -> str | None:
        row = self.q1("SELECT value FROM meta WHERE key = ?", (key,))
        return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    # --- programs ------------------------------------------------------------

    def program(self, key_or_id: str | int) -> sqlite3.Row | None:
        if isinstance(key_or_id, int) or str(key_or_id).isdigit():
            return self.q1("SELECT * FROM programs WHERE id = ?", (int(key_or_id),))
        return self.q1("SELECT * FROM programs WHERE key = ?", (key_or_id,))

    def program_by_url(self, url: str) -> sqlite3.Row | None:
        return self.q1("SELECT * FROM programs WHERE canonical_url = ?", (canonical_url(url),))

    def programs(self, status: str | None = None) -> list[sqlite3.Row]:
        if status:
            return self.q("SELECT * FROM programs WHERE status = ? ORDER BY provider, name", (status,))
        return self.q("SELECT * FROM programs ORDER BY provider, name")

    def insert_program(self, *, key: str, provider: str, name: str, category: str, url: str,
                       official_domains: list[str], source: str, notes: str = "") -> int:
        cur = self.conn.execute(
            """INSERT INTO programs (key, provider, name, category, official_url, canonical_url,
                   official_domains_json, source, status, first_seen_at, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'unverified', ?, ?)""",
            (key, provider, name, category, url, canonical_url(url), dumps(sorted(set(official_domains))),
             source, utcnow_iso(), notes),
        )
        self.log("program_added", "program", cur.lastrowid, key=key, source=source, url=url)
        return int(cur.lastrowid)

    def update_program(self, program_id: int, **cols: Any) -> None:
        if not cols:
            return
        sets = ", ".join(f"{c} = ?" for c in cols)
        self.conn.execute(f"UPDATE programs SET {sets} WHERE id = ?", (*cols.values(), program_id))

    def add_snapshot(self, program_id: int, url: str, content_hash: str | None,
                     details: dict, changes: list[dict]) -> None:
        self.conn.execute(
            """INSERT INTO program_snapshots (program_id, fetched_at, url, content_hash, details_json, changes_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (program_id, utcnow_iso(), url, content_hash, dumps(details), dumps(changes)),
        )

    # --- applications --------------------------------------------------------

    def application(self, app_id: int) -> sqlite3.Row | None:
        return self.q1("SELECT * FROM applications WHERE id = ?", (app_id,))

    def applications(self, statuses: tuple[str, ...] | None = None) -> list[sqlite3.Row]:
        if statuses:
            marks = ",".join("?" * len(statuses))
            return self.q(f"SELECT * FROM applications WHERE status IN ({marks}) ORDER BY id", statuses)
        return self.q("SELECT * FROM applications ORDER BY id")

    def applications_for_program(self, program_id: int) -> list[sqlite3.Row]:
        return self.q("SELECT * FROM applications WHERE program_id = ? ORDER BY id", (program_id,))

    def active_application(self, program_id: int) -> sqlite3.Row | None:
        marks = ",".join("?" * len(ACTIVE_APP_STATUSES))
        return self.q1(
            f"SELECT * FROM applications WHERE program_id = ? AND status IN ({marks})",
            (program_id, *ACTIVE_APP_STATUSES),
        )

    def insert_application(self, *, program_id: int, status: str, packet: dict, packet_hash: str,
                           profile_hash: str, program_details_hash: str | None, missing: list,
                           eligibility: dict) -> int:
        now = utcnow_iso()
        try:
            cur = self.conn.execute(
                """INSERT INTO applications (program_id, status, packet_json, packet_hash, profile_hash,
                       program_details_hash, missing_json, eligibility_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (program_id, status, dumps(packet), packet_hash, profile_hash, program_details_hash,
                 dumps(missing), dumps(eligibility), now, now),
            )
        except sqlite3.IntegrityError as exc:
            raise DuplicateApplication(f"já existe inscrição ativa para o programa {program_id}") from exc
        self.log("application_created", "application", cur.lastrowid, program_id=program_id, status=status)
        return int(cur.lastrowid)

    def update_application(self, app_id: int, **cols: Any) -> None:
        cols["updated_at"] = utcnow_iso()
        sets = ", ".join(f"{c} = ?" for c in cols)
        self.conn.execute(f"UPDATE applications SET {sets} WHERE id = ?", (*cols.values(), app_id))

    def transition(self, app_id: int, from_status: str, to_status: str, **cols: Any) -> bool:
        """Atomic compare-and-set on the status; returns False if someone else moved it."""
        cols["status"] = to_status
        cols["updated_at"] = utcnow_iso()
        sets = ", ".join(f"{c} = ?" for c in cols)
        cur = self.conn.execute(
            f"UPDATE applications SET {sets} WHERE id = ? AND status = ?",
            (*cols.values(), app_id, from_status),
        )
        if cur.rowcount == 1:
            self.log("application_status", "application", app_id, frm=from_status, to=to_status)
            return True
        return False

    # --- credits -------------------------------------------------------------

    def insert_credit(self, *, provider: str, amount: float, currency: str, source: str,
                      program_id: int | None = None, application_id: int | None = None,
                      description: str = "", granted_at: str | None = None, expires_at: str | None = None,
                      evidence: str | None = None, email_message_id: str | None = None) -> int | None:
        try:
            cur = self.conn.execute(
                """INSERT INTO credits (program_id, application_id, provider, description, amount, currency,
                       granted_at, expires_at, source, evidence, email_message_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (program_id, application_id, provider, description, float(amount), currency.upper() or "USD",
                 granted_at, expires_at, source, evidence, email_message_id, utcnow_iso()),
            )
        except sqlite3.IntegrityError:
            return None  # same e-mail already produced this credit
        self.log("credit_added", "credit", cur.lastrowid, provider=provider, amount=amount, currency=currency)
        return int(cur.lastrowid)

    def credits_with_balance(self) -> list[dict]:
        rows = self.q(
            """SELECT c.*, p.key AS program_key, p.name AS program_name,
                      COALESCE((SELECT SUM(u.amount) FROM credit_usage u WHERE u.credit_id = c.id), 0) AS used
               FROM credits c LEFT JOIN programs p ON p.id = c.program_id
               ORDER BY COALESCE(c.expires_at, '9999-12-31'), c.id"""
        )
        today = date.today().isoformat()
        out = []
        for r in rows:
            d = dict(r)
            d["remaining"] = round(d["amount"] - d["used"], 2)
            if d["expires_at"] and d["expires_at"] < today:
                d["state"] = "expired"
            elif d["remaining"] <= 0:
                d["state"] = "exhausted"
            elif d["used"] > 0:
                d["state"] = "partially_used"
            else:
                d["state"] = "available"
            out.append(d)
        return out

    def add_usage(self, credit_id: int, amount: float, used_at: str, note: str = "") -> int:
        if self.q1("SELECT id FROM credits WHERE id = ?", (credit_id,)) is None:
            raise KeyError(f"crédito {credit_id} não existe")
        cur = self.conn.execute(
            "INSERT INTO credit_usage (credit_id, used_at, amount, note, created_at) VALUES (?, ?, ?, ?, ?)",
            (credit_id, used_at, float(amount), note, utcnow_iso()),
        )
        self.log("credit_used", "credit", credit_id, amount=amount, used_at=used_at)
        return int(cur.lastrowid)

    # --- e-mails -------------------------------------------------------------

    def email_processed(self, message_id: str) -> bool:
        return self.q1("SELECT 1 FROM emails_processed WHERE message_id = ?", (message_id,)) is not None

    def record_email(self, *, message_id: str, received_at: str | None, from_addr: str, subject: str,
                     authenticated: bool, action: str, program_id: int | None = None,
                     application_id: int | None = None, classification: dict | None = None) -> None:
        self.conn.execute(
            """INSERT OR IGNORE INTO emails_processed (message_id, received_at, from_addr, subject, authenticated,
                   program_id, application_id, classification_json, action, processed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (message_id, received_at, from_addr, subject, int(authenticated), program_id, application_id,
             dumps(classification) if classification else None, action, utcnow_iso()),
        )
