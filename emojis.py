"""
emojis.py — Premium custom-emoji manager.

Loads `emojis_country.json` (ISO-2 → custom emoji ID) and
`emojis_service.json` (service code → custom emoji ID) from the
project root and exposes:

  * country_emoji_id(iso)           → str | None
  * service_emoji_id(service)       → str | None
  * country_emoji_html(iso, ucode)  → HTML <tg-emoji> wrapper
  * service_emoji_html(svc, ucode)  → HTML <tg-emoji> wrapper

Custom emojis only render when the bot account has Telegram Premium
(or owns Fragment usernames).  When the IDs aren't honoured, every
recipient still sees the Unicode fallback we pass in, so nothing
breaks for non-Premium bots / users.

The JSON files are also tolerant of missing keys — every helper
returns `None` when an ID isn't found and the caller falls back to
the Unicode-only path automatically.
"""

from __future__ import annotations

import html
import json
import logging
import os
import re
from typing import Iterable

log = logging.getLogger("bot.emojis")

_BASE = os.path.dirname(os.path.abspath(__file__))
_COUNTRY_FILE = os.path.join(_BASE, "emojis_country.json")
_SERVICE_FILE = os.path.join(_BASE, "emojis_service.json")

_COUNTRY: dict[str, str] = {}
_SERVICE: dict[str, str] = {}

# UI-emoji table: Unicode emoji char → premium custom-emoji id.
# Populated by main.py at startup via `set_ui_ids(UI_EMOJI_IDS)`.
_UI: dict[str, str] = {}
_UI_PATTERN: re.Pattern[str] | None = None


def _load_one(path: str, label: str) -> dict[str, str]:
    if not os.path.exists(path):
        log.warning("emojis: %s not found at %s — fallbacks only", label, path)
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:                       # noqa: BLE001
        log.warning("emojis: failed to load %s: %s", path, e)
        return {}
    if not isinstance(data, dict):
        log.warning("emojis: %s root must be an object — got %s",
                    path, type(data).__name__)
        return {}
    out: dict[str, str] = {}
    for k, v in data.items():
        if isinstance(k, str) and isinstance(v, (str, int)):
            out[k.strip().upper()] = str(v).strip()
    log.info("emojis: loaded %d entries from %s", len(out), label)
    return out


def reload() -> None:
    """(Re)load both JSON tables.  Useful if the JSONs are updated
    while the bot is running — call from an admin command.
    """
    global _COUNTRY, _SERVICE                    # noqa: PLW0603
    _COUNTRY = _load_one(_COUNTRY_FILE, "emojis_country.json")
    _SERVICE = _load_one(_SERVICE_FILE, "emojis_service.json")


reload()


# ────────────────────────────────────────────────────────────────────
# Public API
# ────────────────────────────────────────────────────────────────────
def country_emoji_id(iso: str | None) -> str | None:
    """ISO-2 → premium custom-emoji document id, or None."""
    if not iso:
        return None
    return _COUNTRY.get(iso.strip().upper())


def service_emoji_id(service: str | None) -> str | None:
    """Service code (`WS`, `FB`, `TG`, …) → premium emoji id, or None.
    Looks up case-insensitively; supports both the short codes
    (`WS`, `FB`) and the long-form names (`whatsapp`, `signal`).

    Lookup order:
      1. PostgreSQL-backed RAM cache (``db.SERVICE_EMOJIS``) populated
         from the ``service_emojis`` table on startup.  This is the
         authoritative source once the bot has connected to PG.
      2. JSON file fallback (``emojis_service.json``) — only used
         pre-PG-init or when the table is empty (first run, before
         the seeder runs).
    """
    if not service:
        return None
    s_upper = service.strip().upper()
    s_lower = service.strip().lower()

    # 1) PG-backed cache (authoritative).  Imported lazily to avoid a
    #    circular import at module load.
    try:
        import db as _db  # noqa: PLC0415
        eid = _db.SERVICE_EMOJIS.get(s_lower)
        if eid:
            return eid
    except Exception:                                 # noqa: BLE001
        pass

    # 2) JSON fallback (compat with first-run seeding & legacy paths).
    if s_upper in _SERVICE:
        return _SERVICE[s_upper]
    for k, v in _SERVICE.items():
        if k.lower() == s_lower:
            return v
    # Common synonyms
    syn = {
        "WHATSAPP": "WS",
        "FACEBOOK": "FB",
        "TELEGRAM": "TG",
        "INSTAGRAM": "IG",
        "MICROSOFT": "MS",
        "GOOGLE": "G",
        "GMAIL": "G",
    }.get(s_upper)
    if syn:
        return _SERVICE.get(syn)
    return None


def country_keys() -> Iterable[str]:
    return _COUNTRY.keys()


def service_keys() -> Iterable[str]:
    return _SERVICE.keys()


# ────────────────────────────────────────────────────────────────────
# HTML <tg-emoji> wrappers — used inside message text only
# (button labels can't render entities).
# ────────────────────────────────────────────────────────────────────
def tg_emoji_html(emoji_id: str | None, fallback: str) -> str:
    """Return either `<tg-emoji emoji-id="…">fallback</tg-emoji>` or
    just the fallback text — depending on whether we have an id.
    Fallback is HTML-escaped; the emoji-id is always numeric.
    """
    safe = html.escape(fallback or "")
    if not emoji_id:
        return safe
    return f'<tg-emoji emoji-id="{emoji_id}">{safe}</tg-emoji>'


def country_emoji_html(iso: str | None, fallback: str) -> str:
    return tg_emoji_html(country_emoji_id(iso), fallback)


def service_emoji_html(service: str | None, fallback: str) -> str:
    return tg_emoji_html(service_emoji_id(service), fallback)


# ────────────────────────────────────────────────────────────────────
# UI-emoji premium wrapping
# ────────────────────────────────────────────────────────────────────
def set_ui_ids(table: dict[str, str]) -> None:
    """Register the UI-emoji ID table.  Call once at startup with
    the `UI_EMOJI_IDS` dict from main.py.  Empty IDs are dropped so
    the wrapper never injects `<tg-emoji emoji-id="">…</tg-emoji>`
    (which Telegram rejects).
    """
    global _UI, _UI_PATTERN                          # noqa: PLW0603
    _UI = {k: str(v).strip() for k, v in (table or {}).items()
           if k and str(v).strip()}
    if _UI:
        # Build a single regex that matches any of the registered
        # Unicode emojis.  Keys are sorted longest-first so multi-
        # codepoint emojis (e.g. flags) are preferred over their
        # individual parts.
        keys = sorted(_UI.keys(), key=len, reverse=True)
        _UI_PATTERN = re.compile("|".join(re.escape(k) for k in keys))
    else:
        _UI_PATTERN = None
    log.info("emojis: UI-emoji table registered with %d entries", len(_UI))


def ui(unicode_emoji: str) -> str:
    """Return `<tg-emoji>fallback</tg-emoji>` HTML for a single UI
    emoji, or just the Unicode emoji if no ID is registered.
    """
    eid = _UI.get(unicode_emoji)
    return tg_emoji_html(eid, unicode_emoji) if eid else unicode_emoji


def ui_id(unicode_emoji: str | None) -> str | None:
    """Return the registered premium custom-emoji ID for a single
    Unicode emoji, or ``None`` when no ID is registered.  Used by
    keyboard-button builders to attach ``icon_custom_emoji_id``.
    """
    if not unicode_emoji:
        return None
    return _UI.get(unicode_emoji) or None


def first_emoji_id(text: str | None) -> str | None:
    """Scan ``text`` and return the premium custom-emoji ID for the
    first Unicode emoji that has one registered in the UI table.

    Used to auto-attach ``icon_custom_emoji_id`` to KeyboardButton /
    InlineKeyboardButton from the leading emoji in the button text,
    so the button label reads like a single premium icon + text on
    Premium clients (and falls back to plain Unicode otherwise).

    Returns ``None`` when ``text`` is empty, no UI table is loaded,
    or no registered emoji appears anywhere in the text.
    """
    if not text or _UI_PATTERN is None:
        return None
    m = _UI_PATTERN.search(text)
    if not m:
        return None
    return _UI.get(m.group(0)) or None


def premium_html(text: str) -> str:
    """Wrap every registered UI emoji in `text` with its `<tg-emoji>`
    HTML tag.  Used as the last step before sending any HTML message
    so the same source string renders as plain Unicode (when no IDs
    are registered) or as premium custom emojis (when they are).

    Already-wrapped emojis (anything inside an existing `<tg-emoji>`
    tag) are left untouched, so calling this twice on the same
    string is a no-op.
    """
    if not text or _UI_PATTERN is None:
        return text or ""
    # Split the string on existing <tg-emoji ...>...</tg-emoji>
    # blocks so we don't touch HTML markup that's already there.
    parts = re.split(
        r"(<tg-emoji\s+emoji-id=\"[^\"]+\">.*?</tg-emoji>)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    out: list[str] = []
    for chunk in parts:
        if not chunk:
            continue
        if chunk.startswith("<tg-emoji"):
            out.append(chunk)
            continue
        out.append(_UI_PATTERN.sub(
            lambda m: tg_emoji_html(_UI.get(m.group(0)), m.group(0)),
            chunk,
        ))
    return "".join(out)
