# OTP Forwarding Bot — Supabase / PostgreSQL Refactor

Production-grade rewrite of the original `main122.py`.
Same OTP pipeline, but **fully Supabase-native** — every piece of
persistent state lives in PostgreSQL behind a pooled `asyncpg` driver
with auto-reconnect, SSL-aware pooling, ultra-fast parallel
broadcasting, premium custom-emoji UI throughout, and clean
import/export tooling for the user database.

## Stack

| Concern              | Library                  |
|----------------------|--------------------------|
| Bot handlers         | `aiogram>=3.28` (Bot API 9.4+) |
| MTProto group reader | `pyrogram>=2.0`          |
| MTProto acceleration | `TgCrypto>=1.2`          |
| Persistence          | `asyncpg>=0.29` (PostgreSQL) |

## Files

- **`db.py`** — `asyncpg`-backed PostgreSQL layer.  Pooled connections
  (`min=5`, `max=30`, `command_timeout=60`), connection retries on
  startup, **SSL auto-enabled** for managed providers (Supabase / RDS /
  Neon / Render / Azure / Timescale Cloud / CockroachDB Cloud — honours
  any explicit `?sslmode=…` in the DSN), schema with indexes on
  `users`, `numbers`, `otps_log`, `processed_messages`,
  `broadcast_logs`, atomic number assignment via `SELECT … FOR UPDATE
  SKIP LOCKED`, fire-and-forget write queue (single writer coroutine
  batches every drain into one transaction, with retry on transient
  errors), `stream_user_ids()` for RAM-safe broadcast over millions of
  users, PG-backed Pyrogram message dedupe (`processed_messages`
  table), persisted broadcast statistics (`broadcast_logs` table),
  premium emoji map (`service_emojis` table — bootstrapped from
  `emojis_service.json` on first run), and per-user ban list
  (`banned_users` table).
- **`core.py`** — country DB (195 entries), OTP parser, premium
  keyboards/cards, daily-stats helpers, force-join helpers, ultra-fast
  parallel broadcast engine (semaphore + gather, 50–200 in-flight).
- **`emojis.py`** — premium custom-emoji manager (loads
  `emojis_country.json` + `emojis_service.json` once at startup, all
  lookups are dict reads — never read from disk per OTP).
- **`emojis_country.json`** / **`emojis_service.json`** — country-flag
  and service custom-emoji ID tables.
- **`main.py`** — aiogram v3 handlers, Pyrogram MTProto listener, OTP
  worker pool, owner panel (Broadcast / Admin Management / Import Users
  / Export Users / Log Forwarding / Force Join), runtime entrypoint.
- **`requirements.txt`** — dependencies.

> All configuration (`BOT_TOKEN`, `OWNER_ID`, `API_ID`, `API_HASH`,
> `USER_PHONE`, `USER_2FA`, `PYRO_SESSION`, `OTP_GROUP_IDS`,
> `OTP_VIEW_URL`, `DATABASE_URL`, `DB_POOL_MIN`, `DB_POOL_MAX`,
> `DB_COMMAND_TIMEOUT`, `OTP_WORKER_COUNT`, `BROADCAST_CONCURRENCY`,
> `BROADCAST_PROGRESS_EVERY`) lives as plain Python constants at the
> top of `main.py` — no `.env` file is read.  Edit the values
> directly to point the bot at your stack.

## UI / UX (Bot API 9.4+ premium)

- **Button colours** via `style="success" / "primary" / "danger"`:
  Get Number / View OTP / Confirm green, navigation / Change Number
  blue, Change Country / Cancel / Clear / Withdraw / out-of-stock red.
- **Custom emoji icons** on every button via `icon_custom_emoji_id`,
  loaded from the JSON files.  No duplicate flags — the Unicode flag is
  removed from the button text whenever an `icon_custom_emoji_id` is
  set, so Premium clients render exactly one flag per row.
- **Service-emoji OTP button** — when the country is added with a
  service token (`India +91 ws`), the OTP delivery message shows a
  one-tap copy button with **only** the OTP digits as text plus the
  premium service emoji as the button icon.  Missing service ⇒ button
  shows the OTP digits alone.  Never crashes the keyboard.
- **Custom emojis in message text** (OTP card / Active Number panel /
  Stock Check / Force-join screen) via
  `<tg-emoji emoji-id="…">unicode-fallback</tg-emoji>` HTML entities.
- **OTP delivery card** — minimal premium layout:
  ```
  ✅ OTP Received!

  🌍 Country: 🇪🇬 Egypt
  📞 Number:  +201253754099
  💵 Earned:  +0.01 rs
  💰 Balance: 0.03 rs
  ```
  No service text line, no time line, no separators inside the card.
- **Active Number panel** — minimal premium layout with live stock:
  ```
  ━━━━━━━━━━━━━━
  📲 Active Number

  🌍 Country: 🇪🇬 Egypt +20

  📞 Left Stock : 5
  ⏳ Status: Waiting OTP…
  ```
  Buttons: `🌍 Change Country` (red), `🔄 Change Number` (blue),
  `👁 View OTP` (green).
- **Country format** now stores `country + dial_code + service` —
  e.g. `INDIA +91 WS`, `RUSSIA +7 9 WS`, `JAMAICA FAST +1 876 FB`.
  Service tokens are optional and accept short (`WS`) or long
  (`WHATSAPP`) forms.

## Owner panel: Import / Export users

Owner taps `📥 Import Users`, then sends a `.txt` or `.csv` file of
user IDs.  Both layouts are accepted simultaneously: one ID per line
**and** comma-separated IDs.  Duplicates are deduped, invalid tokens
counted, and the bot replies with `imported / duplicates / invalid /
total` counts.  Bulk insert via PostgreSQL `unnest()` + `ON CONFLICT
DO NOTHING` — handles huge files without blocking.

Owner taps `📤 Export Users` to receive a `.txt` document of every
user ID (one per line) with the total count in the caption.

## Ultra-fast broadcast

- One bounded `asyncio.Semaphore(BROADCAST_CONCURRENCY)` (default
  `100`, configurable 50–200) caps in-flight sends.
- The producer **streams** user IDs from PostgreSQL via a server-side
  cursor (`prefetch=2000`) — the user list never has to live in RAM.
- A separate timer task edits the progress message every ~1.5 s, so
  the per-send loop is never blocked on Telegram edits.
- FloodWait is parsed from the exception (or `retry_after` attr) and
  the send is retried after the exact requested delay.
- Dead users (blocked / deleted / deactivated) are pruned from
  PostgreSQL and the in-memory cache in batches of 200.
- Broadcast runs as a top-level task, so OTPs / callbacks / messages
  keep flowing through unaffected.
- Reports `Delivered / Blocked / Deleted / Invalid / FloodWait /
  Speed (msg/s) / Elapsed`.

Both plain text broadcasts (with HTML & premium emoji entities) and
**`copy_message`-based** media broadcasts (photo / video / animation
/ document / caption / inline keyboards preserved verbatim) are
supported through the same pipeline.

## Run

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# Edit the constants at the top of main.py:
#   BOT_TOKEN, OWNER_ID, API_ID, API_HASH, USER_PHONE, USER_2FA,
#   OTP_GROUP_IDS, DATABASE_URL (Supabase / Postgres DSN), …
python main.py
```

First run:

1. Connects to PostgreSQL using `DATABASE_URL`.  SSL is auto-enabled
   for managed providers (Supabase / RDS / Neon / Render / Azure /
   Timescale Cloud / CockroachDB Cloud); otherwise honours an explicit
   `?sslmode=…` in the DSN.  Connection is retried with exponential
   backoff to absorb Supabase cold-start delay.
2. Creates the schema if the tables don't exist:  `users`, `admins`,
   `countries`, `numbers`, `otps_log`, `payouts`, `kv`,
   `force_join_chats`, `bot_known_chats`, `daily_stats_today`,
   `daily_stats_history`, `service_emojis`, `processed_messages`,
   `broadcast_logs`, `banned_users`, `user_sessions`, `bot_stats`,
   plus the `withdrawals` view (alias of `payouts`).
3. **One-shot SQLite migration:** if `bot.db` is present alongside
   `main.py`, every row is imported.  Idempotent — re-runs do nothing
   on top of an already-populated PG.  No JSON migration runs.
4. **Service-emoji bootstrap:** if `service_emojis` is empty,
   `emojis_service.json` is loaded into the table on startup.  After
   that the table is the source of truth — JSON edits no longer
   matter.
5. Pyrogram logs in interactively the first time using `USER_PHONE` +
   `USER_2FA`.  Subsequent runs reuse `user_session.session` (or paste
   a string session into `PYRO_SESSION` at the top of `main.py` to
   skip files entirely).

## Performance notes

- **OTP pipeline:** Pyrogram pushes each group message into an
  `asyncio.Queue` (cap 10 000).  `OTP_WORKERS` (default 8) coroutines
  drain it concurrently; user-notification happens *before* any DB
  write.
- **Number assignment:** atomic — `SELECT id, phone FROM numbers WHERE
  available=TRUE ORDER BY id FOR UPDATE SKIP LOCKED LIMIT $1`,
  followed by `UPDATE … SET available=FALSE, assigned_to=$1,
  assigned_at=$2`.  Two concurrent users can never receive the same
  phone number.  Released numbers (Cancel / Clear Prefix / Change
  Number) flip back to `available=TRUE` and rejoin the pool.
- **Persistence:** hot-path mutations live in memory.  A single
  dedicated writer coroutine batches enqueued SQL into one transaction
  per drain cycle — no fsync stall in the OTP path.
- **Catch-up on reconnect:** after the user-session reconnects,
  missed messages per chat are fetched and replayed through the same
  filter pipeline.
- **Pyrogram dedupe:** RAM-first hot path (5-min cooldown), mirrored
  fire-and-forget into the `processed_messages` PG table.  On startup
  the last hour of rows is replayed into RAM, so a restart never
  re-forwards an OTP that was already delivered.  A daily janitor
  prunes rows older than 24 h.

## Supabase deployment

```env
DATABASE_URL=postgresql://postgres:PASS@db.xxxx.supabase.co:5432/postgres
```

For projects behind the Supabase **pooler**, use the pooler URL
(`pgbouncer.supabase.co:6543`) — `asyncpg` works against it directly.
Disable the per-statement cache via `?statement_cache_size=0` in the
DSN if you point at the transaction-mode pooler.

The schema is applied with `CREATE TABLE IF NOT EXISTS …`, so dropping
the bot into an empty Supabase project just works — no migrations to
run, no `init.sql` to apply.
