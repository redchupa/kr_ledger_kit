"""SQLite storage for the ledger. Blocking: call from an executor thread."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from .ledger import Candidate
from .models import Direction, SourceKind

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS raw_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT NOT NULL UNIQUE,
    content_hash TEXT NOT NULL,
    entity_id TEXT,
    package TEXT NOT NULL,
    title TEXT,
    body TEXT,
    sub_text TEXT,
    post_time TEXT NOT NULL,
    status TEXT NOT NULL,
    parser TEXT,
    reason TEXT,
    transaction_id INTEGER,
    dismissed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_raw_content ON raw_notifications(content_hash, post_time);
CREATE INDEX IF NOT EXISTS idx_raw_status ON raw_notifications(status);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at TEXT NOT NULL,
    date TEXT NOT NULL,
    time_known INTEGER NOT NULL DEFAULT 1,
    kind TEXT NOT NULL,
    direction TEXT NOT NULL,
    amount TEXT NOT NULL,
    currency TEXT NOT NULL DEFAULT 'KRW',
    merchant TEXT,
    account_label TEXT,
    issuer TEXT,
    method TEXT,
    installment TEXT,
    category TEXT,
    memo TEXT,
    balance INTEGER,
    cumulative INTEGER,
    is_cancel INTEGER NOT NULL DEFAULT 0,
    source_priority INTEGER NOT NULL DEFAULT 0,
    source_kinds TEXT NOT NULL DEFAULT '[]',
    raw_ids TEXT NOT NULL DEFAULT '[]',
    manual INTEGER NOT NULL DEFAULT 0,
    edited INTEGER NOT NULL DEFAULT 0,
    deleted INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tx_date ON transactions(date);
CREATE INDEX IF NOT EXISTS idx_tx_occurred ON transactions(occurred_at);

CREATE TABLE IF NOT EXISTS schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issuer TEXT,
    title TEXT NOT NULL,
    amount TEXT,
    due_date TEXT,
    raw_id INTEGER,
    created_at TEXT NOT NULL,
    UNIQUE(issuer, title, amount, due_date)
);

CREATE TABLE IF NOT EXISTS merchant_categories (
    merchant TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT NOT NULL UNIQUE,
    name TEXT,
    issuer TEXT,
    method TEXT,
    owner_type TEXT NOT NULL DEFAULT 'personal',
    include INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
"""

TX_COLUMNS = (
    "id", "occurred_at", "date", "time_known", "kind", "direction", "amount", "currency", "merchant",
    "account_label", "issuer", "method", "installment", "category", "memo", "balance", "cumulative",
    "is_cancel", "source_priority", "source_kinds", "raw_ids", "manual", "edited", "deleted",
    "created_at", "updated_at",
)  # fmt: skip

EDITABLE_TX_FIELDS = {"kind", "amount", "merchant", "category", "memo", "account_label", "occurred_at", "currency"}


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _iso(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


class LedgerStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None

    # ------------------------------------------------------------ lifecycle
    def open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
        conn.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
        conn.commit()
        self._conn = conn

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("store is not open")
        return self._conn

    def _exec(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self.conn.execute(sql, tuple(params))
            self.conn.commit()
            return cur

    def _query(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self.conn.execute(sql, tuple(params)).fetchall()

    def get_meta(self, key: str) -> str | None:
        rows = self._query("SELECT value FROM meta WHERE key = ?", (key,))
        return rows[0]["value"] if rows else None

    def set_meta(self, key: str, value: str) -> None:
        self._exec("INSERT INTO meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))

    # ------------------------------------------------------------ raw
    def raw_exists(self, fingerprint: str) -> bool:
        return bool(self._query("SELECT 1 FROM raw_notifications WHERE fingerprint = ?", (fingerprint,)))

    def recent_same_content(self, content_hash: str, since: datetime) -> sqlite3.Row | None:
        rows = self._query(
            "SELECT * FROM raw_notifications WHERE content_hash = ? AND post_time >= ? ORDER BY id DESC LIMIT 1",
            (content_hash, _iso(since)),
        )
        return rows[0] if rows else None

    def insert_raw(self, **fields: Any) -> int:
        fields = {k: _iso(v) for k, v in fields.items()}
        fields.setdefault("created_at", _now())
        cols = ", ".join(fields)
        marks = ", ".join("?" for _ in fields)
        cur = self._exec(f"INSERT INTO raw_notifications ({cols}) VALUES ({marks})", fields.values())
        return int(cur.lastrowid)

    def update_raw(self, raw_id: int, **fields: Any) -> None:
        sets = ", ".join(f"{k} = ?" for k in fields)
        self._exec(f"UPDATE raw_notifications SET {sets} WHERE id = ?", [*map(_iso, fields.values()), raw_id])

    def list_raw(self, status: str, include_dismissed: bool = False, limit: int = 200) -> list[dict]:
        sql = "SELECT * FROM raw_notifications WHERE status = ?"
        if not include_dismissed:
            sql += " AND dismissed = 0"
        sql += " ORDER BY post_time DESC LIMIT ?"
        return [dict(r) for r in self._query(sql, (status, limit))]

    def count_raw(self, status: str) -> int:
        return int(self._query("SELECT COUNT(*) AS n FROM raw_notifications WHERE status = ? AND dismissed = 0", (status,))[0]["n"])

    def purge_raw(self, before: datetime) -> int:
        cur = self._exec(
            "DELETE FROM raw_notifications WHERE post_time < ? AND status != 'unparsed'",
            (_iso(before),),
        )
        return cur.rowcount

    # ------------------------------------------------------------ transactions
    def insert_transaction(self, **fields: Any) -> int:
        now = _now()
        fields.setdefault("created_at", now)
        fields.setdefault("updated_at", now)
        for key in ("source_kinds", "raw_ids"):
            if isinstance(fields.get(key), (list, set, tuple)):
                fields[key] = json.dumps(sorted({str(v) for v in fields[key]}) if key == "source_kinds" else list(fields[key]))
        fields = {k: _iso(v) for k, v in fields.items()}
        if "date" not in fields:
            fields["date"] = str(fields["occurred_at"])[:10]
        cols = ", ".join(fields)
        marks = ", ".join("?" for _ in fields)
        cur = self._exec(f"INSERT INTO transactions ({cols}) VALUES ({marks})", fields.values())
        return int(cur.lastrowid)

    def update_transaction(self, tx_id: int, **fields: Any) -> None:
        if not fields:
            return
        for key in ("source_kinds", "raw_ids"):
            if isinstance(fields.get(key), (list, set, tuple)):
                fields[key] = json.dumps(sorted({str(v) for v in fields[key]}) if key == "source_kinds" else list(fields[key]))
        if "occurred_at" in fields:
            fields["date"] = _iso(fields["occurred_at"])[:10]
        fields["updated_at"] = _now()
        sets = ", ".join(f"{k} = ?" for k in fields)
        self._exec(f"UPDATE transactions SET {sets} WHERE id = ?", [*map(_iso, fields.values()), tx_id])

    def get_transaction(self, tx_id: int) -> dict | None:
        rows = self._query("SELECT * FROM transactions WHERE id = ?", (tx_id,))
        return _tx_dict(rows[0]) if rows else None

    def candidates(self, around: datetime, hours: float = 36) -> list[Candidate]:
        lo = _iso(around - timedelta(hours=hours))
        hi = _iso(around + timedelta(hours=hours))
        rows = self._query(
            "SELECT * FROM transactions WHERE deleted = 0 AND manual = 0 AND occurred_at BETWEEN ? AND ?",
            (lo, hi),
        )
        out = []
        for r in rows:
            out.append(
                Candidate(
                    id=r["id"],
                    amount=Decimal(r["amount"]),
                    currency=r["currency"],
                    direction=Direction(r["direction"]),
                    is_cancel=bool(r["is_cancel"]),
                    occurred_at=datetime.fromisoformat(r["occurred_at"]),
                    time_known=bool(r["time_known"]),
                    source_kinds={SourceKind(k) for k in json.loads(r["source_kinds"])},
                    cumulative=r["cumulative"],
                    issuer=r["issuer"],
                )
            )
        return out

    def bank_transfer_partner(self, tx: dict, minutes: float = 10) -> dict | None:
        """Opposite-direction bank transaction with the same amount close in time."""
        at = datetime.fromisoformat(tx["occurred_at"])
        rows = self._query(
            """SELECT * FROM transactions
               WHERE deleted = 0 AND method = 'bank' AND id != ? AND amount = ? AND currency = ?
                 AND direction != ? AND kind IN ('expense', 'income') AND occurred_at BETWEEN ? AND ?""",
            (
                tx["id"], tx["amount"], tx["currency"], tx["direction"],
                _iso(at - timedelta(minutes=minutes)), _iso(at + timedelta(minutes=minutes)),
            ),
        )  # fmt: skip
        return _tx_dict(rows[0]) if rows else None

    def list_transactions(self, start: date, end: date, include_deleted: bool = False) -> list[dict]:
        sql = """SELECT t.*, a.name AS account_name, a.include AS account_include, a.owner_type AS account_owner_type
                 FROM transactions t LEFT JOIN accounts a ON a.label = t.account_label
                 WHERE t.date BETWEEN ? AND ?"""
        if not include_deleted:
            sql += " AND t.deleted = 0"
        sql += " ORDER BY t.occurred_at DESC, t.id DESC"
        return [_tx_dict(r) for r in self._query(sql, (start.isoformat(), end.isoformat()))]

    def daily_totals(self, start: date, end: date) -> dict[str, dict[str, float]]:
        rows = self._query(
            """SELECT t.date AS d, t.kind AS kind, SUM(CAST(t.amount AS REAL)) AS total, COUNT(*) AS n
               FROM transactions t LEFT JOIN accounts a ON a.label = t.account_label
               WHERE t.deleted = 0 AND t.currency = 'KRW' AND COALESCE(a.include, 1) = 1
                 AND t.date BETWEEN ? AND ?
               GROUP BY t.date, t.kind""",
            (start.isoformat(), end.isoformat()),
        )
        out: dict[str, dict[str, float]] = {}
        for r in rows:
            day = out.setdefault(r["d"], {"expense": 0, "income": 0, "refund": 0, "transfer": 0, "count": 0})
            day[r["kind"]] = r["total"] or 0
            day["count"] += r["n"]
        for day in out.values():
            day["net_expense"] = day["expense"] - day["refund"]
        return out

    def category_totals(self, start: date, end: date) -> list[dict]:
        rows = self._query(
            """SELECT COALESCE(t.category, '미분류') AS category,
                      SUM(CASE WHEN t.kind = 'expense' THEN CAST(t.amount AS REAL)
                               WHEN t.kind = 'refund' THEN -CAST(t.amount AS REAL) ELSE 0 END) AS total,
                      COUNT(*) AS n
               FROM transactions t LEFT JOIN accounts a ON a.label = t.account_label
               WHERE t.deleted = 0 AND t.currency = 'KRW' AND COALESCE(a.include, 1) = 1
                 AND t.kind IN ('expense', 'refund') AND t.date BETWEEN ? AND ?
               GROUP BY COALESCE(t.category, '미분류') ORDER BY total DESC""",
            (start.isoformat(), end.isoformat()),
        )
        return [dict(r) for r in rows]

    def foreign_totals(self, start: date, end: date) -> list[dict]:
        rows = self._query(
            """SELECT currency, SUM(CASE WHEN kind='refund' THEN -CAST(amount AS REAL) ELSE CAST(amount AS REAL) END) AS total,
                      COUNT(*) AS n
               FROM transactions WHERE deleted = 0 AND currency != 'KRW' AND kind IN ('expense','refund')
                 AND date BETWEEN ? AND ? GROUP BY currency""",
            (start.isoformat(), end.isoformat()),
        )
        return [dict(r) for r in rows]

    def last_transaction(self) -> dict | None:
        rows = self._query("SELECT * FROM transactions WHERE deleted = 0 ORDER BY occurred_at DESC, id DESC LIMIT 1")
        return _tx_dict(rows[0]) if rows else None

    # ------------------------------------------------------------ schedules
    def insert_schedule(self, issuer: str | None, title: str, amount: Decimal | None, due: date | None, raw_id: int | None) -> int | None:
        cur = self._exec(
            "INSERT OR IGNORE INTO schedules (issuer, title, amount, due_date, raw_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (issuer or "", title, _iso(amount) if amount is not None else "", _iso(due) if due else "", raw_id, _now()),
        )
        return int(cur.lastrowid) if cur.rowcount else None

    def list_schedules(self, start: date, end: date) -> list[dict]:
        rows = self._query(
            "SELECT * FROM schedules WHERE due_date BETWEEN ? AND ? ORDER BY due_date",
            (start.isoformat(), end.isoformat()),
        )
        return [dict(r) for r in rows]

    # ------------------------------------------------------------ learned categories
    def merchant_category(self, merchant: str | None) -> str | None:
        if not merchant:
            return None
        rows = self._query("SELECT category FROM merchant_categories WHERE merchant = ?", (merchant,))
        return rows[0]["category"] if rows else None

    def learn_category(self, merchant: str, category: str | None) -> None:
        if not merchant:
            return
        if not category:
            self._exec("DELETE FROM merchant_categories WHERE merchant = ?", (merchant,))
            return
        self._exec(
            """INSERT INTO merchant_categories (merchant, category, updated_at) VALUES (?, ?, ?)
               ON CONFLICT(merchant) DO UPDATE SET category = excluded.category, updated_at = excluded.updated_at""",
            (merchant, category, _now()),
        )

    def apply_learned_category(self, merchant: str, category: str) -> int:
        """Recategorise existing, not hand-edited rows of that merchant."""
        cur = self._exec(
            "UPDATE transactions SET category = ?, updated_at = ? WHERE merchant = ? AND edited = 0 AND kind IN ('expense', 'refund')",
            (category, _now(), merchant),
        )
        return cur.rowcount

    def list_categories(self) -> list[str]:
        rows = self._query("SELECT DISTINCT category FROM transactions WHERE category IS NOT NULL AND deleted = 0")
        return sorted(r["category"] for r in rows)

    # ------------------------------------------------------------ accounts
    def ensure_account(self, label: str, issuer: str | None, method: str | None) -> None:
        self._exec(
            "INSERT OR IGNORE INTO accounts (label, name, issuer, method, created_at) VALUES (?, ?, ?, ?, ?)",
            (label, label, issuer, method, _now()),
        )

    def list_accounts(self) -> list[dict]:
        rows = self._query(
            """SELECT a.*, COUNT(t.id) AS tx_count, MAX(t.occurred_at) AS last_used
               FROM accounts a LEFT JOIN transactions t ON t.account_label = a.label AND t.deleted = 0
               GROUP BY a.id ORDER BY a.method, a.label"""
        )
        return [dict(r) for r in rows]

    def update_account(self, account_id: int, **fields: Any) -> None:
        allowed = {k: v for k, v in fields.items() if k in {"name", "owner_type", "include"}}
        if not allowed:
            return
        sets = ", ".join(f"{k} = ?" for k in allowed)
        self._exec(f"UPDATE accounts SET {sets} WHERE id = ?", [*allowed.values(), account_id])


def _tx_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["source_kinds"] = json.loads(d.get("source_kinds") or "[]")
    d["raw_ids"] = json.loads(d.get("raw_ids") or "[]")
    for key in ("time_known", "is_cancel", "manual", "edited", "deleted"):
        if key in d:
            d[key] = bool(d[key])
    if "account_include" in d and d["account_include"] is not None:
        d["account_include"] = bool(d["account_include"])
    try:
        amt = Decimal(d["amount"])
        d["amount"] = int(amt) if amt == amt.to_integral_value() else float(amt)
    except (ArithmeticError, TypeError, ValueError):
        pass
    return d
