"""Transactional checkpoints, exact-result caches and cross-run spend admission.

There are two independent SQLite files: results/cache and a shared spend ledger.
Keeping the ledger outside a cold-result cache prevents cold experiments from
silently resetting expenditure. Unknown bills retain their full reservation.
"""
from __future__ import annotations

import gzip
import json
import sqlite3
import zlib
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING
from pathlib import Path
from typing import Any


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


# Result records, calls, and text-cache payloads use this binary envelope.
# Legacy JSON TEXT remains readable; task_cache and the ledger are untouched.
COMPRESSED_JSON_PREFIX = b"SPJZ1\x00"


def compress_json_text(serialized: str) -> bytes:
    """Pack exact UTF-8 JSON bytes; migration does not reformat old evidence."""
    raw = serialized.encode("utf-8")
    return COMPRESSED_JSON_PREFIX + zlib.compress(raw, level=6)


def stored_json_text(value: str | bytes | bytearray | memoryview) -> str:
    """Read legacy JSON TEXT and versioned compressed BLOB payloads."""
    if isinstance(value, str):
        return value
    raw = bytes(value)
    if raw.startswith(COMPRESSED_JSON_PREFIX):
        raw = zlib.decompress(raw[len(COMPRESSED_JSON_PREFIX):])
    return raw.decode("utf-8")


def encode_stored_json(value: Any) -> bytes:
    return compress_json_text(canonical(value))


def decode_stored_json(value: str | bytes | bytearray | memoryview) -> Any:
    return json.loads(stored_json_text(value))


def register_storage_functions(conn: sqlite3.Connection) -> None:
    """Enable explicit JSON SQL queries on mixed legacy/packed result rows."""
    conn.create_function("stored_json_text", 1, stored_json_text, deterministic=True)


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(path: str | Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection):
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        conn.rollback()
        raise
    else:
        conn.commit()


class BudgetExceeded(RuntimeError):
    """Admission stopped before a request could incur a charge."""


class BudgetLedger:
    """Integer nano-USD accounting; all admissions serialize transactionally."""

    SCALE = Decimal("1000000000")

    def __init__(self, path: str | Path):
        self.conn = _connect(path)
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS spend (
          request_id TEXT PRIMARY KEY, run_id TEXT NOT NULL,
          reserved_nano INTEGER NOT NULL CHECK(reserved_nano>=0),
          charged_nano INTEGER, state TEXT NOT NULL,
          created_at TEXT NOT NULL, settled_at TEXT
        );
        CREATE INDEX IF NOT EXISTS spend_run ON spend(run_id);
        CREATE TABLE IF NOT EXISTS spend_provider (request_id TEXT PRIMARY KEY, provider TEXT NOT NULL);
        """)
        self._ensure_provider_admission_cache()

    def _ensure_provider_admission_cache(self) -> None:
        """Index provider admission without duplicating monetary balances.

        spend_provider remains the authoritative provider mapping. Triggers
        maintain its denormalized tag; all money is still summed directly from
        the original integer spend columns inside the admission transaction.
        Existing connections using the old positional INSERT fail closed after
        migration; they must be stopped before deploying this schema revision.
        """
        with transaction(self.conn):
            columns = {row[1] for row in self.conn.execute("PRAGMA table_info(spend)")}
            added = "admission_provider" not in columns
            if added:
                self.conn.execute("ALTER TABLE spend ADD COLUMN admission_provider TEXT")
                self.conn.execute("""UPDATE spend SET admission_provider=(
                    SELECT provider FROM spend_provider p WHERE p.request_id=spend.request_id)""")
            statements = (
                """CREATE TRIGGER IF NOT EXISTS spend_provider_admission_insert_v1
                   AFTER INSERT ON spend_provider BEGIN
                     UPDATE spend SET admission_provider=NEW.provider WHERE request_id=NEW.request_id;
                   END""",
                """CREATE TRIGGER IF NOT EXISTS spend_provider_admission_delete_v1
                   AFTER DELETE ON spend_provider BEGIN
                     UPDATE spend SET admission_provider=NULL WHERE request_id=OLD.request_id;
                   END""",
                """CREATE TRIGGER IF NOT EXISTS spend_provider_admission_update_v1
                   AFTER UPDATE ON spend_provider BEGIN
                     UPDATE spend SET admission_provider=(SELECT provider FROM spend_provider p
                       WHERE p.request_id=spend.request_id)
                       WHERE request_id IN (OLD.request_id,NEW.request_id);
                   END""",
                """CREATE TRIGGER IF NOT EXISTS spend_admission_insert_v1
                   AFTER INSERT ON spend BEGIN
                     UPDATE spend SET admission_provider=(SELECT provider FROM spend_provider p
                       WHERE p.request_id=NEW.request_id) WHERE request_id=NEW.request_id;
                   END""",
                """CREATE INDEX IF NOT EXISTS spend_commitment_cover_v1
                   ON spend(charged_nano,reserved_nano)""",
                """CREATE INDEX IF NOT EXISTS spend_run_commitment_cover_v1
                   ON spend(run_id,charged_nano,reserved_nano)""",
                """CREATE INDEX IF NOT EXISTS spend_provider_commitment_cover_v1
                   ON spend(admission_provider,charged_nano,reserved_nano)""",
            )
            for statement in statements:
                self.conn.execute(statement)
            mismatches = self.conn.execute("""SELECT COUNT(*) FROM spend s
                LEFT JOIN spend_provider p ON s.request_id=p.request_id
                WHERE s.admission_provider IS NOT p.provider""").fetchone()[0]
            if mismatches:
                raise RuntimeError("Provider admission cache disagrees with the authoritative ledger mapping")

    @classmethod
    def _nano(cls, usd: float | Decimal) -> int:
        value = Decimal(str(usd))
        if not value.is_finite() or value < 0:
            raise ValueError("Budget amounts must be finite and nonnegative")
        return int((value * cls.SCALE).to_integral_value(rounding=ROUND_CEILING))

    def totals(self, run_id: str | None = None) -> dict:
        where, params = (" WHERE run_id=?", (run_id,)) if run_id is not None else ("", ())
        row = self.conn.execute("""SELECT
          COALESCE(SUM(COALESCE(charged_nano,0)),0) AS spent,
          COALESCE(SUM(CASE WHEN state='reserved' THEN reserved_nano ELSE 0 END),0) AS reserved,
          COALESCE(SUM(CASE WHEN state='unknown' THEN reserved_nano ELSE 0 END),0) AS unknown,
          COUNT(*) AS attempts FROM spend""" + where, params).fetchone()
        return {"spent_usd": row["spent"] / 1e9, "reserved_usd": row["reserved"] / 1e9,
                "unknown_charge_hold_usd": row["unknown"] / 1e9,
                "committed_usd": (row["spent"] + row["reserved"] + row["unknown"]) / 1e9,
                "attempts": row["attempts"]}

    def reserve(self, request_id: str, run_id: str, amount_usd: float,
                *, global_cap_usd: float, run_cap_usd: float, provider: str | None = None,
                provider_cap_usd: float | None = None) -> None:
        amount = self._nano(amount_usd)
        if provider_cap_usd is not None and not provider:
            raise ValueError("Provider cap requires a provider name")
        caps = [(None, self._nano(global_cap_usd)), (run_id, self._nano(run_cap_usd))]
        with transaction(self.conn):
            for selected_run, cap in caps:
                where, args = (" WHERE run_id=?", (selected_run,)) if selected_run else ("", ())
                current = self.conn.execute("SELECT COALESCE(SUM(COALESCE(charged_nano, reserved_nano)),0) FROM spend" + where, args).fetchone()[0]
                if current + amount > cap:
                    scope = "global" if selected_run is None else "run"
                    raise BudgetExceeded(f"{scope} budget: committed ${current / 1e9:.6f} + next reservation ${amount / 1e9:.6f} exceeds ${cap / 1e9:.2f}")
            if provider_cap_usd is not None:
                cap = self._nano(provider_cap_usd)
                # Historical untagged attempts count conservatively against each
                # provider cap; they are never silently assumed to be free.
                # Two disjoint covering-index ranges preserve the historical
                # rule that every untagged reservation counts against each cap.
                current = self.conn.execute("""SELECT
                    (SELECT COALESCE(SUM(COALESCE(charged_nano,reserved_nano)),0)
                     FROM spend WHERE admission_provider=?) +
                    (SELECT COALESCE(SUM(COALESCE(charged_nano,reserved_nano)),0)
                     FROM spend WHERE admission_provider IS NULL)""", (provider,)).fetchone()[0]
                if current + amount > cap:
                    raise BudgetExceeded(f"{provider} provider budget exceeds ${cap / 1e9:.2f}")
            self.conn.execute("""INSERT INTO spend
                (request_id,run_id,reserved_nano,charged_nano,state,created_at,settled_at)
                VALUES(?,?,?,?,?,?,?)""", (request_id, run_id, amount, None, "reserved", utcnow(), None))
            if provider:
                self.conn.execute("INSERT INTO spend_provider VALUES(?,?)", (request_id,provider))

    def settle(self, request_id: str, actual_usd: float | None) -> None:
        """Unknown usage is never converted to zero spend; preserve its hold."""
        value = None if actual_usd is None else self._nano(actual_usd)
        with transaction(self.conn):
            old = self.conn.execute("SELECT state FROM spend WHERE request_id=?", (request_id,)).fetchone()
            if old is None:
                raise KeyError(request_id)
            if old["state"] != "reserved":
                raise ValueError("A call may be settled only once; audit reconciliation requires a separate action")
            self.conn.execute("UPDATE spend SET charged_nano=?, state=?, settled_at=? WHERE request_id=?", (value, "unknown" if value is None else "settled", utcnow(), request_id))

    def close(self):
        self.conn.close()


class ResultStore:
    def __init__(self, path: str | Path):
        self.conn = _connect(path)
        register_storage_functions(self.conn)
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS records (
          config TEXT NOT NULL, review_id TEXT NOT NULL, source_sha TEXT NOT NULL,
          text_hash TEXT NOT NULL, record_json TEXT NOT NULL,
          PRIMARY KEY(config, review_id)
        );
        CREATE TABLE IF NOT EXISTS text_cache (
          config TEXT NOT NULL, text_hash TEXT NOT NULL, origin_id TEXT NOT NULL,
          value_json TEXT NOT NULL, PRIMARY KEY(config,text_hash)
        );
        CREATE TABLE IF NOT EXISTS task_cache (
          cache_key TEXT PRIMARY KEY, role TEXT NOT NULL, value_json TEXT NOT NULL,
          request_id TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS calls (
          request_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, value_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS calls_run ON calls(run_id);
        CREATE TABLE IF NOT EXISTS task_references (run_id TEXT NOT NULL, request_id TEXT NOT NULL, PRIMARY KEY(run_id,request_id));
        """)

    def record(self, config: str, review_id: str) -> dict | None:
        row = self.conn.execute("SELECT record_json FROM records WHERE config=? AND review_id=?", (config, review_id)).fetchone()
        return decode_stored_json(row[0]) if row else None

    def cached(self, config: str, text_hash: str) -> dict | None:
        row = self.conn.execute("SELECT origin_id,value_json FROM text_cache WHERE config=? AND text_hash=?", (config, text_hash)).fetchone()
        return {"origin_id": row[0], "value": decode_stored_json(row[1])} if row else None

    def save_record(self, config: str, text_hash: str, record: dict, *, cache_value: dict | None = None) -> None:
        serialized = canonical(record)
        if cache_value is None:
            prior = self.conn.execute("SELECT record_json FROM records WHERE config=? AND review_id=?", (config, record["review_id"])).fetchone()
            if prior and stored_json_text(prior[0]) == serialized:
                return
        with transaction(self.conn):
            self.conn.execute("INSERT OR REPLACE INTO records VALUES(?,?,?,?,?)", (config, record["review_id"], record["source_sha256"], text_hash, compress_json_text(serialized)))
            if cache_value is not None:
                if record["status"] != "completed" or record.get("cache_source_id"):
                    raise ValueError("Only a completed direct original can establish a text cache")
                self.conn.execute("INSERT OR REPLACE INTO text_cache VALUES(?,?,?,?)", (config, text_hash, record["review_id"], encode_stored_json(cache_value)))

    def save_call(self, call: dict):
        with transaction(self.conn):
            self.conn.execute("INSERT OR REPLACE INTO calls VALUES(?,?,?)", (call["request_id"], call["run_id"], encode_stored_json(call)))

    def calls(self, run_id: str | None = None) -> list[dict]:
        if run_id:
            rows = self.conn.execute("SELECT value_json FROM calls WHERE run_id=? ORDER BY rowid", (run_id,)).fetchall()
        else:
            rows = self.conn.execute("SELECT value_json FROM calls ORDER BY rowid").fetchall()
        return [decode_stored_json(row[0]) for row in rows]

    def task_references(self, run_id: str):
        return {row[0] for row in self.conn.execute("SELECT request_id FROM task_references WHERE run_id=?", (run_id,))}

    def save_task_reference(self, run_id: str, request_id: str):
        self.conn.execute("INSERT OR IGNORE INTO task_references VALUES(?,?)", (run_id, request_id))

    def task(self, key: str) -> dict | None:
        row = self.conn.execute("SELECT value_json,request_id FROM task_cache WHERE cache_key=?", (key,)).fetchone()
        return {"value": json.loads(row[0]), "request_id": row[1]} if row else None

    def save_task(self, key: str, role: str, value: dict, request_id: str):
        with transaction(self.conn):
            self.conn.execute("INSERT OR REPLACE INTO task_cache VALUES(?,?,?,?,?)", (key, role, canonical(value), request_id, utcnow()))

    def close(self):
        self.conn.close()


def atomic_json(path: str | Path, value: Any):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def atomic_jsonl(path: str | Path, values):
    """Atomically export canonical JSONL, losslessly gzipped for a .gz path.

    The alternate format is removed only after its replacement is complete.
    This prevents a stale plain export from shadowing a newer compressed one.
    SQLite remains the durable request/result journal during export.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        opener = gzip.open if path.suffix == ".gz" else open
        options = {"compresslevel": 6} if path.suffix == ".gz" else {}
        with opener(temporary, "wt", encoding="utf-8", newline="\n", **options) as handle:
            for value in values:
                handle.write(canonical(value) + "\n")
        temporary.replace(path)
        alternate = path.with_suffix("") if path.suffix == ".gz" else path.with_name(path.name + ".gz")
        alternate.unlink(missing_ok=True)
    finally:
        temporary.unlink(missing_ok=True)


def resolve_jsonl(path: str | Path) -> Path:
    """Resolve an explicit JSONL path, accepting its compressed sibling."""
    path = Path(path)
    if path.exists() or path.suffix == ".gz":
        return path
    compressed = path.with_name(path.name + ".gz")
    return compressed if compressed.exists() else path


def open_jsonl(path: str | Path):
    """Open plain or gzip JSONL as UTF-8 text; caller owns the context."""
    path = resolve_jsonl(path)
    opener = gzip.open if path.suffix == ".gz" else open
    return opener(path, "rt", encoding="utf-8")


def open_jsonl_bytes(path: str | Path):
    """Open the original JSONL bytes, transparently decompressing if needed."""
    path = resolve_jsonl(path)
    opener = gzip.open if path.suffix == ".gz" else open
    return opener(path, "rb")


def read_jsonl(path: str | Path):
    """Yield JSONL values without materializing a second large text copy."""
    path = resolve_jsonl(path)
    expected_bytes = path.stat().st_size
    with open_jsonl(path) as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid {path.name} line {line_number}") from exc
        # iCloud can return an immediate EOF for a nonempty offloaded file.
        # Check physical source progress, including gzip's underlying stream,
        # so silent short reads cannot become empty evaluation/cost evidence.
        consumed_bytes = handle.buffer.fileobj.tell() if path.suffix == ".gz" else handle.tell()
        if consumed_bytes < expected_bytes:
            raise OSError(f"Incomplete JSONL read for {path}: consumed {consumed_bytes} of "
                          f"{expected_bytes} source bytes; hydrate the exact file and retry")


def reserve_request_slot(ledger: BudgetLedger, provider: str, requests_per_second: float,
                         estimated_tokens: int = 0, tokens_per_second: float = 20000) -> float:
    """Shared request/token pacing using conservative estimated token admission.

    The token estimate is a scheduling bound, never billed/provider usage.
    Reservations serialize across workers, engines and processes sharing ledger.
    """
    import time
    if requests_per_second <= 0 or tokens_per_second <= 0 or estimated_tokens < 0:
        raise ValueError("Pacing limits must be positive and estimates nonnegative")
    conn = ledger.conn
    conn.execute("CREATE TABLE IF NOT EXISTS admission_pacing(provider TEXT PRIMARY KEY, next_request_at REAL NOT NULL, next_token_at REAL NOT NULL)")
    with transaction(conn):
        row = conn.execute("SELECT next_request_at,next_token_at FROM admission_pacing WHERE provider=?", (provider,)).fetchone()
        now = time.time()
        slot = max(now, row[0] if row else now, row[1] if row else now)
        conn.execute("INSERT OR REPLACE INTO admission_pacing VALUES(?,?,?)",
                     (provider, slot + 1.0 / requests_per_second, slot + estimated_tokens / tokens_per_second))
    return max(0.0, slot - now)
