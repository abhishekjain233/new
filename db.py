"""
db.py — Async PostgreSQL (Supabase) persistence layer for the OTP bot.

  * Single shared `asyncpg` connection pool — every handler grabs a
    connection only for the duration of a query and releases it.
    SSL-aware (auto-`ssl=require` for hostnames matching Supabase /
    AWS RDS / etc.), `command_timeout=60`, statement cache 2048.
  * In-memory caches (USERS / COUNTRIES / PAYOUTS / …) keep the SAME
    public shape so call-sites that do
    `users[user_id]["balance"] += price` keep working unchanged.
  * Hot-path mutations are non-blocking: callers fire `db.save_X(...)`
    which enqueues an UPSERT and returns immediately.  A single
    dedicated writer coroutine drains the queue and groups bursts into
    one transaction per cycle, with retry on transient errors.
  * Numbers live in their own `numbers` table — one row per phone —
    with `available / assigned_to / assigned_at` tracking.  Assignment
    uses `SELECT … FOR UPDATE SKIP LOCKED` so two concurrent requests
    can never claim the same number.
  * Pyrogram message dedupe (`processed_messages`) is PG-backed with a
    UNIQUE `(chat_id, message_id)` constraint — survives restarts and
    is naturally burst-safe.
  * Premium service emojis live in `service_emojis`; on first run the
    table is seeded from `emojis_service.json` and cached in RAM.
  * Broadcast statistics are persisted in `broadcast_logs`.
  * One-time legacy migration from the old `bot.db` (aiosqlite) is
    available via `LEGACY_SQLITE_PATH` env var — on by default if the
    file is present in CWD.  No JSON-file fallback any more.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence
from urllib.parse import urlparse

import asyncpg

log = logging.getLogger("bot.db")


# ────────────────────────────────────────────────────────────────────
# Public in-memory state — same shape as the original JSON globals.
# Modules import these dicts and mutate them in place; the writer
# coroutine takes care of persisting changes.
# ────────────────────────────────────────────────────────────────────
USERS: dict[str, dict] = {}
COUNTRIES: dict[str, dict] = {"countries": {}}
PAYOUTS: list[dict] = []
OTPS_LOG: list[dict] = []
CONFIG: dict[str, Any] = {
    "payout_enabled": True,
    "log_group_id": None,
    "log_forwarding_enabled": False,
}
FORCE_JOIN: dict[str, Any] = {"enabled": False, "chats": []}
BOT_KNOWN_CHATS: dict[str, dict] = {}
DAILY_STATS: dict[str, Any] = {"today": {}, "history": {}}
ADMIN_IDS: list[int] = []
SERVICE_EMOJIS: dict[str, str] = {}     # service_key → custom emoji ID
BANNED_USER_IDS: set[int] = set()


# ────────────────────────────────────────────────────────────────────
# Schema
# ────────────────────────────────────────────────────────────────────
SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    user_id          TEXT PRIMARY KEY,
    username         TEXT,
    balance          DOUBLE PRECISION NOT NULL DEFAULT 0,
    otps             INTEGER          NOT NULL DEFAULT 0,
    numbers_taken    JSONB            NOT NULL DEFAULT '[]'::jsonb,
    current_number   TEXT,
    current_numbers  JSONB            NOT NULL DEFAULT '[]'::jsonb,
    current_country  TEXT,
    awaiting_otp     BOOLEAN          NOT NULL DEFAULT FALSE,
    created_at       TIMESTAMPTZ      NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_users_user_id ON users(user_id);

CREATE TABLE IF NOT EXISTS countries (
    key             TEXT PRIMARY KEY,
    display_name    TEXT NOT NULL,
    iso             TEXT,
    dial_code       TEXT,
    prefix          TEXT,
    flag            TEXT,
    service         TEXT,
    price           DOUBLE PRECISION NOT NULL DEFAULT 0.01,
    user_limit      INTEGER          NOT NULL DEFAULT 2,
    total_otps      INTEGER          NOT NULL DEFAULT 0,
    total_earnings  DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    created_at      TEXT
);

CREATE TABLE IF NOT EXISTS numbers (
    id            BIGSERIAL PRIMARY KEY,
    country_key   TEXT      NOT NULL,
    phone         TEXT      NOT NULL,
    available     BOOLEAN   NOT NULL DEFAULT TRUE,
    assigned_to   BIGINT,
    assigned_at   TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(country_key, phone)
);
CREATE INDEX IF NOT EXISTS idx_numbers_country ON numbers(country_key);
CREATE INDEX IF NOT EXISTS idx_numbers_country_avail
    ON numbers(country_key, available);
CREATE INDEX IF NOT EXISTS idx_numbers_assigned_to ON numbers(assigned_to);

CREATE TABLE IF NOT EXISTS payouts (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    amount      DOUBLE PRECISION NOT NULL,
    method      TEXT,
    details     TEXT,
    status      TEXT NOT NULL DEFAULT 'pending',
    created_at  TEXT
);

CREATE TABLE IF NOT EXISTS otps_log (
    id         BIGSERIAL PRIMARY KEY,
    user_id    TEXT,
    number     TEXT,
    otp        TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_otps_user ON otps_log(user_id);
CREATE INDEX IF NOT EXISTS idx_otps_created ON otps_log(created_at);

CREATE TABLE IF NOT EXISTS force_join_chats (
    idx          INTEGER PRIMARY KEY,
    chat_id      BIGINT,
    title        TEXT,
    link         TEXT,
    button_name  TEXT,
    invite_only  BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS bot_known_chats (
    chat_id  BIGINT PRIMARY KEY,
    title    TEXT,
    type     TEXT
);

CREATE TABLE IF NOT EXISTS admins (
    user_id BIGINT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS daily_stats_history (
    date            TEXT PRIMARY KEY,
    total_otps      INTEGER          NOT NULL DEFAULT 0,
    total_earnings  DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    countries       JSONB            NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS daily_stats_today (
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    date            TEXT NOT NULL,
    total_otps      INTEGER          NOT NULL DEFAULT 0,
    total_earnings  DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    countries       JSONB            NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS service_emojis (
    service_key  TEXT PRIMARY KEY,
    emoji_id     TEXT NOT NULL,
    emoji_name   TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS processed_messages (
    chat_id     BIGINT NOT NULL,
    message_id  BIGINT NOT NULL,
    seen_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (chat_id, message_id)
);
CREATE INDEX IF NOT EXISTS idx_processed_messages_seen_at
    ON processed_messages(seen_at);

CREATE TABLE IF NOT EXISTS broadcast_logs (
    id              BIGSERIAL PRIMARY KEY,
    sender_admin    BIGINT,
    content_type    TEXT NOT NULL DEFAULT 'text',
    content         TEXT,
    delivered       INTEGER NOT NULL DEFAULT 0,
    blocked         INTEGER NOT NULL DEFAULT 0,
    deleted         INTEGER NOT NULL DEFAULT 0,
    invalid         INTEGER NOT NULL DEFAULT 0,
    flood           INTEGER NOT NULL DEFAULT 0,
    elapsed_seconds DOUBLE PRECISION,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_broadcast_logs_created_at
    ON broadcast_logs(created_at);

CREATE TABLE IF NOT EXISTS banned_users (
    user_id     BIGINT PRIMARY KEY,
    reason      TEXT,
    banned_by   BIGINT,
    banned_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS bot_stats (
    key       TEXT PRIMARY KEY,
    value     JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- `withdrawals` is the requirements-doc spelling of payouts.  Keep
-- the canonical row data in `payouts` (existing column shape) and
-- expose a view named `withdrawals` so external dashboards / Supabase
-- SQL editors can query either name.  CREATE OR REPLACE VIEW is
-- idempotent so this is safe on every startup.
CREATE OR REPLACE VIEW withdrawals AS
    SELECT id,
           user_id,
           amount,
           method,
           details,
           status,
           created_at
    FROM   payouts;

CREATE TABLE IF NOT EXISTS user_sessions (
    user_id      BIGINT NOT NULL,
    chat_id      BIGINT NOT NULL,
    state_name   TEXT,
    state_data   JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, chat_id)
);
CREATE INDEX IF NOT EXISTS idx_user_sessions_updated_at
    ON user_sessions(updated_at);
"""


# ────────────────────────────────────────────────────────────────────
# Async writer queue — fire-and-forget pattern preserved from the
# aiosqlite layer.  Writes are batched into one transaction per drain
# cycle for high throughput.
# ────────────────────────────────────────────────────────────────────
_pool: asyncpg.Pool | None = None
_dsn: str = ""
_pool_min: int = 5
_pool_max: int = 30

_write_queue: asyncio.Queue[tuple[str, tuple] | None] | None = None
_writer_task: asyncio.Task | None = None
_writer_started: asyncio.Event | None = None


def pool() -> asyncpg.Pool:
    """Return the active pool (must call `init()` first)."""
    if _pool is None:
        raise RuntimeError("db.init() not called yet")
    return _pool


def _enqueue(sql: str, params: Sequence = ()) -> None:
    """Fire-and-forget write.  Never blocks the caller."""
    if _write_queue is None:
        return
    try:
        _write_queue.put_nowait((sql, tuple(params)))
    except asyncio.QueueFull:
        log.error("Writer queue full; dropping write.")


async def _writer_loop() -> None:
    assert _pool is not None
    assert _write_queue is not None and _writer_started is not None
    _writer_started.set()
    while True:
        item = await _write_queue.get()
        if item is None:
            break
        sql, params = item
        # Drain everything queued up so far so we batch them in one
        # transaction.
        batch: list[tuple[str, tuple] | None] = [(sql, params)]
        try:
            while True:
                nxt = _write_queue.get_nowait()
                batch.append(nxt)
                if nxt is None:
                    break
        except asyncio.QueueEmpty:
            pass

        # Retry transient connection issues (Supabase pool reaper, brief
        # network blips, etc.).  Schema/constraint errors fail fast.
        last_err: Exception | None = None
        for attempt in range(1, 4):
            try:
                async with _pool.acquire() as conn:
                    async with conn.transaction():
                        for entry in batch:
                            if entry is None:
                                continue
                            s, p = entry
                            await conn.execute(s, *p)
                last_err = None
                break
            except (asyncpg.PostgresConnectionError,
                    asyncpg.InterfaceError,
                    OSError) as e:
                last_err = e
                wait = min(0.5 * (2 ** (attempt - 1)), 4.0)
                log.warning(
                    "DB write batch transient failure (attempt %d): %s — "
                    "retrying in %.1fs", attempt, e, wait,
                )
                await asyncio.sleep(wait)
            except Exception as e:                    # noqa: BLE001
                last_err = e
                break
        if last_err is not None:
            log.error("DB write batch failed: %s", last_err, exc_info=True)

        if any(entry is None for entry in batch):
            break


# ────────────────────────────────────────────────────────────────────
# Bootstrap
# ────────────────────────────────────────────────────────────────────
def _needs_ssl(dsn: str) -> bool:
    """Auto-enable SSL for managed PG providers (Supabase / RDS / etc.).

    Honours an explicit ``sslmode=…`` / ``ssl=…`` query param verbatim
    (so deployments can force-disable SSL by passing ``sslmode=disable``).
    """
    try:
        u = urlparse(dsn)
    except Exception:                                 # noqa: BLE001
        return False
    qs = (u.query or "").lower()
    if "sslmode=" in qs or "ssl=" in qs:
        return False  # caller already controls it
    host = (u.hostname or "").lower()
    return any(h in host for h in (
        "supabase.co", "supabase.com", "supabase.net",
        "rds.amazonaws.com", "neon.tech", "render.com",
        "azure.com", "cloud.timescale.com", "cockroachlabs.cloud",
    ))


async def init(
    dsn: str,
    *,
    min_size: int = 5,
    max_size: int = 30,
    command_timeout: int = 60,
) -> None:
    """Open the pool, run schema, import legacy data, populate caches.

    SSL is auto-enabled for managed-PG hostnames (Supabase et al.).
    The pool is created with retries to absorb the cold-start delay
    new Supabase projects sometimes exhibit.
    """
    global _pool, _dsn, _pool_min, _pool_max
    global _writer_task, _write_queue, _writer_started

    _dsn = dsn
    _pool_min = min_size
    _pool_max = max_size

    _write_queue = asyncio.Queue()
    _writer_started = asyncio.Event()

    pool_kwargs: dict[str, Any] = dict(
        dsn=dsn,
        min_size=min_size,
        max_size=max_size,
        statement_cache_size=2048,
        command_timeout=float(command_timeout),
    )
    if _needs_ssl(dsn):
        pool_kwargs["ssl"] = "require"
        log.info("PostgreSQL SSL auto-enabled (managed provider detected).")

    last_err: Exception | None = None
    for attempt in range(1, 6):
        try:
            _pool = await asyncpg.create_pool(**pool_kwargs)
            break
        except Exception as e:                        # noqa: BLE001
            last_err = e
            wait = min(2 ** attempt, 10)
            log.warning(
                "PG connect attempt %d failed: %s — retrying in %ds",
                attempt, e, wait,
            )
            await asyncio.sleep(wait)
    if _pool is None:
        raise RuntimeError(
            f"Failed to create asyncpg pool after retries: {last_err}"
        )

    async with _pool.acquire() as conn:
        await conn.execute(SCHEMA)

    await _migrate_from_sqlite_if_present()
    await _seed_service_emojis_if_empty()
    await _load_caches()

    _writer_task = asyncio.create_task(_writer_loop(), name="db-writer")
    await _writer_started.wait()
    log.info("DB ready (users=%d, countries=%d, payouts=%d, services=%d)",
             len(USERS), len(COUNTRIES["countries"]), len(PAYOUTS),
             len(SERVICE_EMOJIS))


async def shutdown() -> None:
    """Flush queue and close the pool cleanly."""
    global _pool
    if _writer_task and not _writer_task.done() and _write_queue is not None:
        await _write_queue.put(None)
        try:
            await asyncio.wait_for(_writer_task, timeout=10)
        except asyncio.TimeoutError:
            log.warning("DB writer didn't shut down in time.")
    if _pool is not None:
        await _pool.close()
        _pool = None


# ────────────────────────────────────────────────────────────────────
# Legacy SQLite migration (aiosqlite era → asyncpg).  One-shot,
# idempotent: only runs when the target tables are still empty AND
# `bot.db` exists in CWD.
# ────────────────────────────────────────────────────────────────────
async def _migrate_from_sqlite_if_present() -> None:
    sqlite_path = os.environ.get("LEGACY_SQLITE_PATH", "bot.db")
    if not os.path.exists(sqlite_path):
        return
    assert _pool is not None

    async with _pool.acquire() as conn:
        users_row = await conn.fetchrow("SELECT 1 FROM users LIMIT 1")
        countries_row = await conn.fetchrow(
            "SELECT 1 FROM countries LIMIT 1")
    if users_row and countries_row:
        return  # Already migrated.

    log.info("Importing legacy SQLite database from %s", sqlite_path)
    try:
        sconn = sqlite3.connect(sqlite_path)
        sconn.row_factory = sqlite3.Row
    except Exception as e:                           # noqa: BLE001
        log.warning("Could not open legacy SQLite DB: %s", e)
        return

    def _safe_query(sql: str) -> list[sqlite3.Row]:
        try:
            cur = sconn.execute(sql)
            return list(cur.fetchall())
        except sqlite3.Error:
            return []

    users_rows     = _safe_query("SELECT * FROM users")
    countries_rows = _safe_query("SELECT * FROM countries")
    payouts_rows   = _safe_query("SELECT * FROM payouts")
    otps_rows      = _safe_query("SELECT * FROM otps_log")
    kv_rows        = _safe_query("SELECT * FROM kv")
    fj_rows        = _safe_query("SELECT * FROM force_join_chats")
    bkc_rows       = _safe_query("SELECT * FROM bot_known_chats")
    adm_rows       = _safe_query("SELECT * FROM admins")
    dst_rows       = _safe_query("SELECT * FROM daily_stats_today")
    dsh_rows       = _safe_query("SELECT * FROM daily_stats_history")
    sconn.close()

    assert _pool is not None
    async with _pool.acquire() as conn:
        async with conn.transaction():
            for r in users_rows:
                await conn.execute(
                    """INSERT INTO users
                       (user_id, username, balance, otps, numbers_taken,
                        current_number, current_numbers, current_country,
                        awaiting_otp)
                       VALUES ($1,$2,$3,$4,$5::jsonb,$6,$7::jsonb,$8,$9)
                       ON CONFLICT (user_id) DO NOTHING""",
                    str(r["user_id"]),
                    r["username"],
                    float(r["balance"] or 0),
                    int(r["otps"] or 0),
                    r["numbers_taken"] or "[]",
                    r["current_number"],
                    r["current_numbers"] or "[]",
                    r["current_country"],
                    bool(r["awaiting_otp"]),
                )
            for r in countries_rows:
                cols = r.keys()
                service_val = r["service"] if "service" in cols else None
                numbers_json = r["numbers"] if "numbers" in cols else "[]"
                key = r["key"]
                await conn.execute(
                    """INSERT INTO countries
                       (key, display_name, iso, dial_code, prefix, flag,
                        service, price, user_limit, total_otps,
                        total_earnings, created_at)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                       ON CONFLICT (key) DO NOTHING""",
                    key,
                    r["display_name"] or key.upper(),
                    r["iso"] or "",
                    r["dial_code"] or "",
                    r["prefix"],
                    r["flag"] or "",
                    service_val,
                    float(r["price"] or 0.01),
                    int(r["user_limit"] or 2),
                    int(r["total_otps"] or 0),
                    float(r["total_earnings"] or 0.0),
                    r["created_at"],
                )
                # Numbers were stored as JSON list inside the country row;
                # split them out into the new `numbers` table.
                try:
                    nums = json.loads(numbers_json or "[]")
                except Exception:                    # noqa: BLE001
                    nums = []
                if nums:
                    await conn.executemany(
                        """INSERT INTO numbers
                           (country_key, phone, available)
                           VALUES ($1, $2, TRUE)
                           ON CONFLICT (country_key, phone) DO NOTHING""",
                        [(key, str(n)) for n in nums if n],
                    )

            for r in payouts_rows:
                await conn.execute(
                    """INSERT INTO payouts
                       (id, user_id, amount, method, details, status,
                        created_at)
                       VALUES ($1,$2,$3,$4,$5,$6,$7)
                       ON CONFLICT (id) DO NOTHING""",
                    str(r["id"]),
                    str(r["user_id"] or ""),
                    float(r["amount"] or 0),
                    r["method"],
                    r["details"],
                    r["status"] or "pending",
                    r["created_at"],
                )

            for r in otps_rows:
                await conn.execute(
                    """INSERT INTO otps_log (user_id, number, otp, created_at)
                       VALUES ($1,$2,$3,$4)""",
                    r["user_id"],
                    r["number"],
                    r["otp"],
                    r["created_at"] or str(int(time.time())),
                )

            for r in kv_rows:
                await conn.execute(
                    """INSERT INTO kv (key, value) VALUES ($1, $2)
                       ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value""",
                    r["key"], r["value"],
                )

            for r in fj_rows:
                await conn.execute(
                    """INSERT INTO force_join_chats
                       (idx, chat_id, title, link, button_name, invite_only)
                       VALUES ($1,$2,$3,$4,$5,$6)
                       ON CONFLICT (idx) DO NOTHING""",
                    int(r["idx"]),
                    int(r["chat_id"]) if r["chat_id"] is not None else None,
                    r["title"], r["link"], r["button_name"],
                    bool(r["invite_only"]),
                )

            for r in bkc_rows:
                await conn.execute(
                    """INSERT INTO bot_known_chats (chat_id, title, type)
                       VALUES ($1,$2,$3)
                       ON CONFLICT (chat_id) DO NOTHING""",
                    int(r["chat_id"]), r["title"], r["type"],
                )

            for r in adm_rows:
                await conn.execute(
                    """INSERT INTO admins (user_id) VALUES ($1)
                       ON CONFLICT (user_id) DO NOTHING""",
                    int(r["user_id"]),
                )

            for r in dst_rows:
                await conn.execute(
                    """INSERT INTO daily_stats_today
                       (id, date, total_otps, total_earnings, countries)
                       VALUES (1,$1,$2,$3,$4::jsonb)
                       ON CONFLICT (id) DO UPDATE SET
                         date           = EXCLUDED.date,
                         total_otps     = EXCLUDED.total_otps,
                         total_earnings = EXCLUDED.total_earnings,
                         countries      = EXCLUDED.countries""",
                    r["date"],
                    int(r["total_otps"] or 0),
                    float(r["total_earnings"] or 0.0),
                    r["countries"] or "{}",
                )

            for r in dsh_rows:
                await conn.execute(
                    """INSERT INTO daily_stats_history
                       (date, total_otps, total_earnings, countries)
                       VALUES ($1,$2,$3,$4::jsonb)
                       ON CONFLICT (date) DO NOTHING""",
                    r["date"],
                    int(r["total_otps"] or 0),
                    float(r["total_earnings"] or 0.0),
                    r["countries"] or "{}",
                )
    log.info("Legacy SQLite import complete: users=%d countries=%d "
             "payouts=%d otps=%d",
             len(users_rows), len(countries_rows), len(payouts_rows),
             len(otps_rows))


# ────────────────────────────────────────────────────────────────────
# Service-emoji seeding — `emojis_service.json` ships with the bot
# and is used as a one-shot bootstrap for the `service_emojis` table.
# After bootstrap the JSON file is irrelevant; updates go through
# `set_service_emoji()` and the table.
# ────────────────────────────────────────────────────────────────────
_EMOJI_SERVICE_PATH = "emojis_service.json"


def _read_json(path: str, default: Any) -> Any:
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:                           # noqa: BLE001
        log.warning("Could not read %s: %s — using default", path, e)
        return default


async def _seed_service_emojis_if_empty() -> None:
    """Bootstrap the `service_emojis` table from the bundled JSON."""
    assert _pool is not None
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT 1 FROM service_emojis LIMIT 1")
        if row:
            return
        data = _read_json(_EMOJI_SERVICE_PATH, {}) or {}
        if not isinstance(data, dict) or not data:
            return
        async with conn.transaction():
            for key, val in data.items():
                if not val:
                    continue
                await conn.execute(
                    """INSERT INTO service_emojis
                       (service_key, emoji_id, emoji_name)
                       VALUES ($1, $2, $3)
                       ON CONFLICT (service_key) DO NOTHING""",
                    str(key).lower().strip(),
                    str(val).strip(),
                    str(key).upper().strip(),
                )
        log.info("Seeded %d service emojis from %s",
                 len(data), _EMOJI_SERVICE_PATH)


# ────────────────────────────────────────────────────────────────────
# Cache loader — populates the in-memory state shared with the rest
# of the bot.  After this returns, hot-path code reads from the dicts.
# ────────────────────────────────────────────────────────────────────
async def _load_caches() -> None:
    assert _pool is not None

    USERS.clear()
    COUNTRIES["countries"] = {}
    PAYOUTS.clear()
    OTPS_LOG.clear()
    BOT_KNOWN_CHATS.clear()
    ADMIN_IDS.clear()
    DAILY_STATS["today"] = {}
    DAILY_STATS["history"] = {}
    FORCE_JOIN["chats"] = []
    FORCE_JOIN["enabled"] = False
    SERVICE_EMOJIS.clear()
    BANNED_USER_IDS.clear()

    async with _pool.acquire() as conn:
        for row in await conn.fetch("SELECT * FROM users"):
            USERS[row["user_id"]] = {
                "username":         row["username"],
                "balance":          float(row["balance"]),
                "otps":             int(row["otps"]),
                "numbers_taken":    _decode_jsonb(row["numbers_taken"]) or [],
                "current_number":   row["current_number"],
                "current_numbers":  _decode_jsonb(row["current_numbers"]) or [],
                "current_country":  row["current_country"],
                "awaiting_otp":     bool(row["awaiting_otp"]),
            }

        for row in await conn.fetch("SELECT * FROM countries"):
            COUNTRIES["countries"][row["key"]] = {
                "display_name":   row["display_name"],
                "iso":            row["iso"],
                "dial_code":      row["dial_code"],
                "prefix":         row["prefix"],
                "flag":           row["flag"],
                "service":        row["service"],
                "numbers":        [],   # filled below from the numbers table
                "price":          float(row["price"]),
                "user_limit":     int(row["user_limit"]),
                "total_otps":     int(row["total_otps"]),
                "total_earnings": float(row["total_earnings"]),
                "created_at":     row["created_at"],
            }

        # Available numbers — feeds the in-memory pool used by hot path.
        for row in await conn.fetch(
            "SELECT country_key, phone FROM numbers "
            "WHERE available = TRUE ORDER BY id"
        ):
            ck = row["country_key"]
            if ck in COUNTRIES["countries"]:
                COUNTRIES["countries"][ck]["numbers"].append(row["phone"])

        for row in await conn.fetch(
            "SELECT * FROM payouts ORDER BY ctid"
        ):
            PAYOUTS.append({
                "id":         row["id"],
                "user":       row["user_id"],
                "amount":     float(row["amount"]),
                "method":     row["method"],
                "details":    row["details"],
                "status":     row["status"],
                "created_at": row["created_at"],
            })

        for row in await conn.fetch(
            "SELECT user_id, number, otp FROM otps_log "
            "ORDER BY id DESC LIMIT 1000"
        ):
            OTPS_LOG.append({
                "user":   row["user_id"],
                "number": row["number"],
                "otp":    row["otp"],
            })
        OTPS_LOG.reverse()

        for row in await conn.fetch("SELECT key, value FROM kv"):
            try:
                v = json.loads(row["value"])
            except Exception:                        # noqa: BLE001
                v = row["value"]
            if row["key"].startswith("config:"):
                CONFIG[row["key"][len("config:"):]] = v
            elif row["key"] == "force_join_enabled":
                FORCE_JOIN["enabled"] = bool(v)
            elif row["key"] == "last_reset_date":
                DAILY_STATS["_last_reset_date"] = v

        for row in await conn.fetch(
            "SELECT * FROM force_join_chats ORDER BY idx"
        ):
            entry = {
                "chat_id":     row["chat_id"],
                "title":       row["title"],
                "link":        row["link"],
                "button_name": row["button_name"],
            }
            if row["invite_only"]:
                entry["invite_only"] = True
            FORCE_JOIN["chats"].append(entry)

        for row in await conn.fetch("SELECT * FROM bot_known_chats"):
            BOT_KNOWN_CHATS[str(row["chat_id"])] = {
                "chat_id": int(row["chat_id"]),
                "title":   row["title"],
                "type":    row["type"],
            }

        for row in await conn.fetch("SELECT user_id FROM admins"):
            ADMIN_IDS.append(int(row["user_id"]))

        row = await conn.fetchrow(
            "SELECT * FROM daily_stats_today WHERE id=1")
        if row:
            DAILY_STATS["today"] = {
                "date":           row["date"],
                "total_otps":     int(row["total_otps"]),
                "total_earnings": float(row["total_earnings"]),
                "countries":      _decode_jsonb(row["countries"]) or {},
            }

        for row in await conn.fetch("SELECT * FROM daily_stats_history"):
            DAILY_STATS["history"][row["date"]] = {
                "total_otps":     int(row["total_otps"]),
                "total_earnings": float(row["total_earnings"]),
                "countries":      _decode_jsonb(row["countries"]) or {},
            }

        for row in await conn.fetch(
            "SELECT service_key, emoji_id FROM service_emojis"
        ):
            sk = (row["service_key"] or "").lower().strip()
            eid = (row["emoji_id"] or "").strip()
            if sk and eid:
                SERVICE_EMOJIS[sk] = eid

        for row in await conn.fetch("SELECT user_id FROM banned_users"):
            try:
                BANNED_USER_IDS.add(int(row["user_id"]))
            except (TypeError, ValueError):
                continue


def _decode_jsonb(value: Any) -> Any:
    """asyncpg returns jsonb as a string by default; tolerate dicts/lists too."""
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:                            # noqa: BLE001
            return None
    return value


# ════════════════════════════════════════════════════════════════════
# Save helpers — fire-and-forget. Mutate the in-memory dict THEN
# call one of these to schedule the write.  Behaviour matches the
# original `save_X(...)` pattern, but never blocks the caller.
# ════════════════════════════════════════════════════════════════════
def save_user(user_id: str) -> None:
    u = USERS.get(user_id)
    if u is None:
        return
    _enqueue(
        """INSERT INTO users
           (user_id, username, balance, otps, numbers_taken,
            current_number, current_numbers, current_country,
            awaiting_otp)
           VALUES ($1,$2,$3,$4,$5::jsonb,$6,$7::jsonb,$8,$9)
           ON CONFLICT (user_id) DO UPDATE SET
             username        = EXCLUDED.username,
             balance         = EXCLUDED.balance,
             otps            = EXCLUDED.otps,
             numbers_taken   = EXCLUDED.numbers_taken,
             current_number  = EXCLUDED.current_number,
             current_numbers = EXCLUDED.current_numbers,
             current_country = EXCLUDED.current_country,
             awaiting_otp    = EXCLUDED.awaiting_otp""",
        (
            user_id,
            u.get("username"),
            float(u.get("balance") or 0),
            int(u.get("otps") or 0),
            json.dumps(u.get("numbers_taken") or []),
            u.get("current_number"),
            json.dumps(u.get("current_numbers") or []),
            u.get("current_country"),
            bool(u.get("awaiting_otp")),
        ),
    )


def save_all_users() -> None:
    for uid in list(USERS.keys()):
        save_user(uid)


def save_country(key: str) -> None:
    """Persist country metadata.  Numbers are persisted separately
    via `add_numbers / mark_numbers_assigned / mark_numbers_available
    / clear_numbers_for_country`.
    """
    c = COUNTRIES["countries"].get(key)
    if not c:
        _enqueue("DELETE FROM countries WHERE key=$1", (key,))
        _enqueue("DELETE FROM numbers   WHERE country_key=$1", (key,))
        return
    _enqueue(
        """INSERT INTO countries
           (key, display_name, iso, dial_code, prefix, flag, service,
            price, user_limit, total_otps, total_earnings, created_at)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
           ON CONFLICT (key) DO UPDATE SET
             display_name   = EXCLUDED.display_name,
             iso            = EXCLUDED.iso,
             dial_code      = EXCLUDED.dial_code,
             prefix         = EXCLUDED.prefix,
             flag           = EXCLUDED.flag,
             service        = EXCLUDED.service,
             price          = EXCLUDED.price,
             user_limit     = EXCLUDED.user_limit,
             total_otps     = EXCLUDED.total_otps,
             total_earnings = EXCLUDED.total_earnings""",
        (
            key,
            c.get("display_name") or key.upper(),
            c.get("iso") or "",
            c.get("dial_code") or "",
            c.get("prefix"),
            c.get("flag") or "",
            c.get("service") or None,
            float(c.get("price") or 0.01),
            int(c.get("user_limit") or 2),
            int(c.get("total_otps") or 0),
            float(c.get("total_earnings") or 0.0),
            c.get("created_at"),
        ),
    )


def delete_country(key: str) -> None:
    COUNTRIES["countries"].pop(key, None)
    _enqueue("DELETE FROM countries WHERE key=$1", (key,))
    _enqueue("DELETE FROM numbers   WHERE country_key=$1", (key,))


def save_all_countries() -> None:
    for key in list(COUNTRIES["countries"].keys()):
        save_country(key)


def save_payout(payout: dict) -> None:
    _enqueue(
        """INSERT INTO payouts
           (id, user_id, amount, method, details, status, created_at)
           VALUES ($1,$2,$3,$4,$5,$6,$7)
           ON CONFLICT (id) DO UPDATE SET
             user_id    = EXCLUDED.user_id,
             amount     = EXCLUDED.amount,
             method     = EXCLUDED.method,
             details    = EXCLUDED.details,
             status     = EXCLUDED.status,
             created_at = EXCLUDED.created_at""",
        (
            str(payout["id"]),
            str(payout.get("user") or ""),
            float(payout.get("amount") or 0),
            payout.get("method"),
            payout.get("details"),
            payout.get("status") or "pending",
            payout.get("created_at"),
        ),
    )


def save_all_payouts() -> None:
    for p in PAYOUTS:
        save_payout(p)


def append_otp_log(user_id: str | None, number: str | None,
                   otp: str | None) -> None:
    OTPS_LOG.append({"user": user_id, "number": number, "otp": otp})
    if len(OTPS_LOG) > 2000:
        del OTPS_LOG[:1000]
    _enqueue(
        """INSERT INTO otps_log (user_id, number, otp, created_at)
           VALUES ($1,$2,$3,$4)""",
        (user_id, number, otp, str(int(time.time()))),
    )


def save_config_key(key: str) -> None:
    _enqueue(
        """INSERT INTO kv (key, value) VALUES ($1, $2)
           ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
        (f"config:{key}", json.dumps(CONFIG.get(key))),
    )


def save_all_config() -> None:
    for k in CONFIG:
        save_config_key(k)


def save_force_join() -> None:
    """Replace force_join_chats from FORCE_JOIN['chats']."""
    _enqueue("DELETE FROM force_join_chats", ())
    for i, e in enumerate(FORCE_JOIN.get("chats", [])):
        _enqueue(
            """INSERT INTO force_join_chats
               (idx, chat_id, title, link, button_name, invite_only)
               VALUES ($1,$2,$3,$4,$5,$6)""",
            (
                i,
                e.get("chat_id"),
                e.get("title"),
                e.get("link"),
                e.get("button_name"),
                bool(e.get("invite_only")),
            ),
        )
    _enqueue(
        """INSERT INTO kv (key, value) VALUES ($1, $2)
           ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
        ("force_join_enabled",
         json.dumps(bool(FORCE_JOIN.get("enabled")))),
    )


def save_bot_known_chat(chat_id: int) -> None:
    info = BOT_KNOWN_CHATS.get(str(chat_id))
    if info is None:
        _enqueue("DELETE FROM bot_known_chats WHERE chat_id=$1", (chat_id,))
        return
    _enqueue(
        """INSERT INTO bot_known_chats (chat_id, title, type)
           VALUES ($1,$2,$3)
           ON CONFLICT (chat_id) DO UPDATE SET
             title = EXCLUDED.title,
             type  = EXCLUDED.type""",
        (int(chat_id), info.get("title"), info.get("type")),
    )


def delete_bot_known_chat(chat_id: int) -> None:
    BOT_KNOWN_CHATS.pop(str(chat_id), None)
    _enqueue("DELETE FROM bot_known_chats WHERE chat_id=$1", (chat_id,))


def save_admins() -> None:
    _enqueue("DELETE FROM admins", ())
    for aid in ADMIN_IDS:
        _enqueue(
            """INSERT INTO admins (user_id) VALUES ($1)
               ON CONFLICT (user_id) DO NOTHING""",
            (int(aid),),
        )


def save_daily_today() -> None:
    today = DAILY_STATS.get("today", {}) or {}
    if not today.get("date"):
        return
    _enqueue(
        """INSERT INTO daily_stats_today
           (id, date, total_otps, total_earnings, countries)
           VALUES (1,$1,$2,$3,$4::jsonb)
           ON CONFLICT (id) DO UPDATE SET
             date           = EXCLUDED.date,
             total_otps     = EXCLUDED.total_otps,
             total_earnings = EXCLUDED.total_earnings,
             countries      = EXCLUDED.countries""",
        (
            today.get("date"),
            int(today.get("total_otps") or 0),
            float(today.get("total_earnings") or 0.0),
            json.dumps(today.get("countries") or {}),
        ),
    )


def save_daily_history(date: str) -> None:
    h = DAILY_STATS["history"].get(date) or {}
    _enqueue(
        """INSERT INTO daily_stats_history
           (date, total_otps, total_earnings, countries)
           VALUES ($1,$2,$3,$4::jsonb)
           ON CONFLICT (date) DO UPDATE SET
             total_otps     = EXCLUDED.total_otps,
             total_earnings = EXCLUDED.total_earnings,
             countries      = EXCLUDED.countries""",
        (
            date,
            int(h.get("total_otps") or 0),
            float(h.get("total_earnings") or 0.0),
            json.dumps(h.get("countries") or {}),
        ),
    )


def save_last_reset_date(date: str) -> None:
    DAILY_STATS["_last_reset_date"] = date
    _enqueue(
        """INSERT INTO kv (key, value) VALUES ($1, $2)
           ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
        ("last_reset_date", json.dumps(date)),
    )


# ════════════════════════════════════════════════════════════════════
#                   NUMBERS  (per-phone tracking)
# ────────────────────────────────────────────────────────────────────
# `numbers` is a separate table with one row per phone number:
#   country_key, phone, available, assigned_to, assigned_at
# These helpers keep the in-memory `COUNTRIES["countries"][k]["numbers"]`
# list (which holds the AVAILABLE pool) in sync with the table.
# ════════════════════════════════════════════════════════════════════
async def add_numbers(country_key: str, phones: Iterable[str]) -> int:
    """Bulk-insert phone numbers as available.  Duplicates ignored.
    Returns the number of NEW rows that were inserted.
    """
    assert _pool is not None
    cleaned: list[str] = []
    seen: set[str] = set()
    for p in phones:
        if not p:
            continue
        s = str(p).strip()
        if not s or s in seen:
            continue
        seen.add(s)
        cleaned.append(s)
    if not cleaned:
        return 0

    async with _pool.acquire() as conn:
        # COUNT new rows: insert ON CONFLICT DO NOTHING returns nothing
        # by default, so we use RETURNING phone and count the result.
        rows = await conn.fetch(
            """INSERT INTO numbers (country_key, phone, available)
               VALUES ($1, unnest($2::text[]), TRUE)
               ON CONFLICT (country_key, phone) DO NOTHING
               RETURNING phone""",
            country_key, cleaned,
        )
    inserted = [r["phone"] for r in rows]

    # Keep the in-memory available pool in sync.
    if country_key in COUNTRIES["countries"]:
        pool_list = COUNTRIES["countries"][country_key].setdefault(
            "numbers", [])
        pool_set = set(pool_list)
        for ph in inserted:
            if ph not in pool_set:
                pool_list.append(ph)
                pool_set.add(ph)
    return len(inserted)


async def assign_numbers(country_key: str, user_id: int,
                         limit: int) -> list[str]:
    """Atomically claim up to `limit` available numbers from `country_key`.

    Uses `SELECT … FOR UPDATE SKIP LOCKED` so two concurrent calls can
    never receive the same number.  Returns the list of assigned phone
    numbers (may be shorter than `limit` if the pool is depleted).
    """
    assert _pool is not None
    if limit <= 0:
        return []
    now = datetime.now(tz=timezone.utc)

    async with _pool.acquire() as conn:
        async with conn.transaction():
            rows = await conn.fetch(
                """SELECT id, phone FROM numbers
                   WHERE country_key = $1 AND available = TRUE
                   ORDER BY id
                   FOR UPDATE SKIP LOCKED
                   LIMIT $2""",
                country_key, limit,
            )
            if not rows:
                return []
            ids = [r["id"] for r in rows]
            phones = [r["phone"] for r in rows]
            await conn.execute(
                """UPDATE numbers
                   SET available = FALSE,
                       assigned_to = $1,
                       assigned_at = $2
                   WHERE id = ANY($3::bigint[])""",
                int(user_id), now, ids,
            )

    # Sync in-memory pool.
    if country_key in COUNTRIES["countries"]:
        pool_list = COUNTRIES["countries"][country_key].setdefault(
            "numbers", [])
        for ph in phones:
            try:
                pool_list.remove(ph)
            except ValueError:
                pass
    return phones


async def release_numbers(country_key: str, phones: Iterable[str]) -> None:
    """Mark each number available again (clears assignment fields)."""
    assert _pool is not None
    cleaned = [str(p) for p in phones if p]
    if not cleaned:
        return
    async with _pool.acquire() as conn:
        await conn.execute(
            """UPDATE numbers
               SET available = TRUE,
                   assigned_to = NULL,
                   assigned_at = NULL
               WHERE country_key = $1 AND phone = ANY($2::text[])""",
            country_key, cleaned,
        )
    if country_key in COUNTRIES["countries"]:
        pool_list = COUNTRIES["countries"][country_key].setdefault(
            "numbers", [])
        existing = set(pool_list)
        for p in cleaned:
            if p not in existing:
                pool_list.append(p)
                existing.add(p)


async def clear_numbers_for_country(country_key: str) -> int:
    """Delete every number row for the country.  Returns rows deleted."""
    assert _pool is not None
    async with _pool.acquire() as conn:
        result: str = await conn.execute(
            "DELETE FROM numbers WHERE country_key = $1", country_key,
        )
    if country_key in COUNTRIES["countries"]:
        COUNTRIES["countries"][country_key]["numbers"] = []
    # asyncpg returns 'DELETE <n>' as the status string.
    parts = (result or "").split()
    try:
        return int(parts[-1]) if parts else 0
    except ValueError:
        return 0


async def count_available_numbers(country_key: str) -> int:
    assert _pool is not None
    async with _pool.acquire() as conn:
        return int(await conn.fetchval(
            """SELECT COUNT(*) FROM numbers
               WHERE country_key = $1 AND available = TRUE""",
            country_key,
        ))


# ════════════════════════════════════════════════════════════════════
#                   USERS  (import / export / streaming)
# ════════════════════════════════════════════════════════════════════
async def bulk_import_users(user_ids: Iterable[int]) -> tuple[int, int]:
    """Insert user rows in bulk.  Returns (imported, skipped_duplicates).

    Used by the Owner panel "Import Users" flow.  Uses a single
    transaction with `INSERT ... ON CONFLICT DO NOTHING RETURNING` so
    we can compute exact insert/dedup counts in one round-trip.
    """
    assert _pool is not None
    seen: set[str] = set()
    cleaned: list[str] = []
    for uid in user_ids:
        try:
            uid_int = int(uid)
        except (TypeError, ValueError):
            continue
        if uid_int <= 0:
            continue
        s = str(uid_int)
        if s in seen:
            continue
        seen.add(s)
        cleaned.append(s)

    if not cleaned:
        return 0, 0

    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            """INSERT INTO users (user_id)
               SELECT unnest($1::text[])
               ON CONFLICT (user_id) DO NOTHING
               RETURNING user_id""",
            cleaned,
        )
    inserted = {r["user_id"] for r in rows}
    skipped = len(cleaned) - len(inserted)

    # Sync in-memory cache so broadcasts pick them up immediately.
    for uid in inserted:
        if uid in USERS:
            continue
        USERS[uid] = {
            "username": None,
            "balance": 0.0,
            "otps": 0,
            "numbers_taken": [],
            "current_number": None,
            "current_numbers": [],
            "current_country": None,
            "awaiting_otp": False,
        }
    return len(inserted), skipped


async def export_user_ids() -> list[str]:
    """Stream every user_id from the table.  Uses a server-side cursor
    so the entire user base never needs to live in RAM at once.
    """
    assert _pool is not None
    out: list[str] = []
    async with _pool.acquire() as conn:
        async with conn.transaction():
            async for row in conn.cursor(
                "SELECT user_id FROM users ORDER BY user_id",
                prefetch=2000,
            ):
                out.append(row["user_id"])
    return out


async def stream_user_ids():
    """Yield user_id strings using a server-side cursor — never loads
    the full user list into RAM.  Designed for the broadcast worker.
    """
    assert _pool is not None
    async with _pool.acquire() as conn:
        async with conn.transaction():
            async for row in conn.cursor(
                "SELECT user_id FROM users",
                prefetch=2000,
            ):
                yield row["user_id"]


async def delete_users(user_ids: Iterable[int]) -> int:
    """Bulk delete user rows (used by the broadcast dead-user pruner)."""
    assert _pool is not None
    cleaned = [str(int(u)) for u in user_ids if str(u).lstrip("-").isdigit()]
    if not cleaned:
        return 0
    async with _pool.acquire() as conn:
        result: str = await conn.execute(
            "DELETE FROM users WHERE user_id = ANY($1::text[])",
            cleaned,
        )
    for uid in cleaned:
        USERS.pop(uid, None)
    parts = (result or "").split()
    try:
        return int(parts[-1]) if parts else 0
    except ValueError:
        return 0


# ────────────────────────────────────────────────────────────────────
# Service-emoji helpers
# ────────────────────────────────────────────────────────────────────
def get_service_emoji(service_key: str) -> str | None:
    """RAM-only lookup; never hits the DB.  Used on every OTP."""
    if not service_key:
        return None
    return SERVICE_EMOJIS.get(service_key.lower().strip()) or None


async def set_service_emoji(service_key: str, emoji_id: str,
                            emoji_name: str | None = None) -> None:
    """Upsert a service-emoji mapping in PG and RAM cache."""
    assert _pool is not None
    sk = (service_key or "").lower().strip()
    eid = (emoji_id or "").strip()
    if not sk or not eid:
        return
    async with _pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO service_emojis (service_key, emoji_id, emoji_name)
               VALUES ($1, $2, $3)
               ON CONFLICT (service_key) DO UPDATE
                  SET emoji_id   = EXCLUDED.emoji_id,
                      emoji_name = EXCLUDED.emoji_name,
                      updated_at = NOW()""",
            sk, eid, emoji_name,
        )
    SERVICE_EMOJIS[sk] = eid


# ────────────────────────────────────────────────────────────────────
# Bans
# ────────────────────────────────────────────────────────────────────
def is_banned(user_id: int | str) -> bool:
    try:
        return int(user_id) in BANNED_USER_IDS
    except (TypeError, ValueError):
        return False


async def ban_user(user_id: int, reason: str | None = None,
                   banned_by: int | None = None) -> None:
    assert _pool is not None
    async with _pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO banned_users (user_id, reason, banned_by)
               VALUES ($1, $2, $3)
               ON CONFLICT (user_id) DO UPDATE
                  SET reason    = EXCLUDED.reason,
                      banned_by = EXCLUDED.banned_by,
                      banned_at = NOW()""",
            int(user_id), reason, banned_by,
        )
    BANNED_USER_IDS.add(int(user_id))


async def unban_user(user_id: int) -> None:
    assert _pool is not None
    async with _pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM banned_users WHERE user_id = $1", int(user_id),
        )
    BANNED_USER_IDS.discard(int(user_id))


# ────────────────────────────────────────────────────────────────────
# Pyrogram message dedupe — backed by `processed_messages` PG table.
# Single-statement INSERT ... ON CONFLICT DO NOTHING returns no row
# when the message has already been processed; that's our dedupe
# signal.  Keeps the dedupe stable across restarts.
# ────────────────────────────────────────────────────────────────────
async def record_processed_message(chat_id: int, message_id: int) -> bool:
    """Returns True if this is the first time we see (chat_id, message_id),
    False if it's a duplicate (already inserted previously).
    """
    assert _pool is not None
    try:
        async with _pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO processed_messages (chat_id, message_id)
                   VALUES ($1, $2)
                   ON CONFLICT (chat_id, message_id) DO NOTHING
                   RETURNING 1""",
                int(chat_id), int(message_id),
            )
        return row is not None
    except Exception as e:                            # noqa: BLE001
        # Never let a dedupe-DB hiccup drop a real OTP — fall open.
        log.warning("record_processed_message failed: %s", e)
        return True


async def prune_processed_messages(older_than_seconds: int = 86400) -> int:
    """Delete dedupe rows older than the cut-off (default 24h)."""
    assert _pool is not None
    async with _pool.acquire() as conn:
        result: str = await conn.execute(
            """DELETE FROM processed_messages
               WHERE seen_at < NOW() - ($1 || ' seconds')::interval""",
            str(int(older_than_seconds)),
        )
    parts = (result or "").split()
    try:
        return int(parts[-1]) if parts else 0
    except ValueError:
        return 0


# ────────────────────────────────────────────────────────────────────
# Broadcast logging
# ────────────────────────────────────────────────────────────────────
async def log_broadcast(
    *,
    sender_admin: int | None,
    content_type: str,
    content: str | None,
    delivered: int,
    blocked: int,
    deleted: int,
    invalid: int,
    flood: int,
    elapsed_seconds: float | None,
) -> int:
    """Persist broadcast statistics.  Returns inserted row id."""
    assert _pool is not None
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO broadcast_logs
               (sender_admin, content_type, content, delivered, blocked,
                deleted, invalid, flood, elapsed_seconds)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
               RETURNING id""",
            sender_admin,
            content_type or "text",
            (content or "")[:8000] if content else None,
            int(delivered or 0),
            int(blocked or 0),
            int(deleted or 0),
            int(invalid or 0),
            int(flood or 0),
            float(elapsed_seconds) if elapsed_seconds is not None else None,
        )
    return int(row["id"]) if row else 0


# ────────────────────────────────────────────────────────────────────
# Bot stats — generic key/value JSONB store
# ────────────────────────────────────────────────────────────────────
async def stats_set(key: str, value: Any) -> None:
    assert _pool is not None
    async with _pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO bot_stats (key, value, updated_at)
               VALUES ($1, $2::jsonb, NOW())
               ON CONFLICT (key) DO UPDATE
                  SET value = EXCLUDED.value,
                      updated_at = NOW()""",
            key, json.dumps(value),
        )


async def stats_get(key: str, default: Any = None) -> Any:
    assert _pool is not None
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT value FROM bot_stats WHERE key = $1", key,
        )
    if not row:
        return default
    return _decode_jsonb(row["value"])
