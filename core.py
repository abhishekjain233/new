"""
core.py — Country database, OTP parser, keyboards, daily-stats helpers,
force-join helpers, broadcast engine, and other shared utilities.

Behaviour-preserving translation of the original `main122.py` helpers
to the new aiogram v3 / Pyrogram / aiosqlite stack:

  * Same COUNTRY_DB (195 entries).
  * Same `parse_country_input()`/`_find_iso_by_prefix()` rules.
  * Same `get_country_label()`.
  * Same OTP detection strategies — but smarter normalisation, more
    tolerant for hyphenated / multiline / mixed-format codes, and
    explicit support for WhatsApp / Telegram / Google patterns.
  * Same OTP delivery message format (Time / Country / Number / OTP /
    Earned / Balance) — preserved exactly.
  * Same daily-stats roll-over rule (IST 05:30, business-day key).
  * Same reply / inline keyboards.
  * Same broadcast engine (concurrent batches, FloodWait handling,
    auto-prune dead users).
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import re
import time
import unicodedata
from zoneinfo import ZoneInfo

from aiogram.types import (
    CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup,
    KeyboardButton, ReplyKeyboardMarkup,
)

import db
import emojis

log = logging.getLogger("bot.core")


# ────────────────────────────────────────────────────────────────────
# Premium-icon button builders
# ────────────────────────────────────────────────────────────────────
# These thin wrappers around aiogram's KeyboardButton /
# InlineKeyboardButton attach `icon_custom_emoji_id` automatically
# from the first registered Unicode emoji that appears in the button
# text.  The Unicode emoji stays in the visible label as a fallback
# for non-Premium clients; Premium clients see the animated custom
# emoji rendered in the button's icon slot instead.
#
# Buttons whose text has no registered emoji (e.g. plain "Cancel")
# fall through to the standard constructor — the icon slot is left
# empty and the button is unchanged.
def _kbtn(text: str,
          *,
          style: str | None = None,
          icon_custom_emoji_id: str | None = None,
          **kwargs) -> KeyboardButton:
    """KeyboardButton with optional auto-attached premium icon.

    `icon_custom_emoji_id` may be passed explicitly (e.g. for a
    service emoji that doesn't appear in `UI_EMOJI_IDS`).  When
    omitted, the first registered emoji in `text` is used.
    """
    eid = icon_custom_emoji_id or emojis.first_emoji_id(text)
    if eid:
        kwargs["icon_custom_emoji_id"] = eid
    if style is not None:
        kwargs["style"] = style
    return KeyboardButton(text=text, **kwargs)


def _ikbtn(text: str,
           *,
           style: str | None = None,
           icon_custom_emoji_id: str | None = None,
           **kwargs) -> InlineKeyboardButton:
    """InlineKeyboardButton with optional auto-attached premium icon.

    Same behaviour as `_kbtn` — first registered emoji in `text`
    becomes the button icon when no explicit ID is supplied.
    """
    eid = icon_custom_emoji_id or emojis.first_emoji_id(text)
    if eid:
        kwargs["icon_custom_emoji_id"] = eid
    if style is not None:
        kwargs["style"] = style
    return InlineKeyboardButton(text=text, **kwargs)


# ────────────────────────────────────────────────────────────────────
# 195-COUNTRY DATABASE (verbatim from main122.py)
# ────────────────────────────────────────────────────────────────────
COUNTRY_DB: dict[str, dict[str, str]] = {
    "afghanistan": {"name": "AFGHANISTAN", "iso": "AF", "dial": "+93"},
    "albania": {"name": "ALBANIA", "iso": "AL", "dial": "+355"},
    "algeria": {"name": "ALGERIA", "iso": "DZ", "dial": "+213"},
    "andorra": {"name": "ANDORRA", "iso": "AD", "dial": "+376"},
    "angola": {"name": "ANGOLA", "iso": "AO", "dial": "+244"},
    "antigua and barbuda": {"name": "ANTIGUA AND BARBUDA", "iso": "AG", "dial": "+1268"},
    "argentina": {"name": "ARGENTINA", "iso": "AR", "dial": "+54"},
    "armenia": {"name": "ARMENIA", "iso": "AM", "dial": "+374"},
    "australia": {"name": "AUSTRALIA", "iso": "AU", "dial": "+61"},
    "austria": {"name": "AUSTRIA", "iso": "AT", "dial": "+43"},
    "azerbaijan": {"name": "AZERBAIJAN", "iso": "AZ", "dial": "+994"},
    "bahamas": {"name": "BAHAMAS", "iso": "BS", "dial": "+1242"},
    "bahrain": {"name": "BAHRAIN", "iso": "BH", "dial": "+973"},
    "bangladesh": {"name": "BANGLADESH", "iso": "BD", "dial": "+880"},
    "barbados": {"name": "BARBADOS", "iso": "BB", "dial": "+1246"},
    "belarus": {"name": "BELARUS", "iso": "BY", "dial": "+375"},
    "belgium": {"name": "BELGIUM", "iso": "BE", "dial": "+32"},
    "belize": {"name": "BELIZE", "iso": "BZ", "dial": "+501"},
    "benin": {"name": "BENIN", "iso": "BJ", "dial": "+229"},
    "bhutan": {"name": "BHUTAN", "iso": "BT", "dial": "+975"},
    "bolivia": {"name": "BOLIVIA", "iso": "BO", "dial": "+591"},
    "bosnia and herzegovina": {"name": "BOSNIA AND HERZEGOVINA", "iso": "BA", "dial": "+387"},
    "botswana": {"name": "BOTSWANA", "iso": "BW", "dial": "+267"},
    "brazil": {"name": "BRAZIL", "iso": "BR", "dial": "+55"},
    "brunei": {"name": "BRUNEI", "iso": "BN", "dial": "+673"},
    "bulgaria": {"name": "BULGARIA", "iso": "BG", "dial": "+359"},
    "burkina faso": {"name": "BURKINA FASO", "iso": "BF", "dial": "+226"},
    "burundi": {"name": "BURUNDI", "iso": "BI", "dial": "+257"},
    "cabo verde": {"name": "CABO VERDE", "iso": "CV", "dial": "+238"},
    "cambodia": {"name": "CAMBODIA", "iso": "KH", "dial": "+855"},
    "cameroon": {"name": "CAMEROON", "iso": "CM", "dial": "+237"},
    "canada": {"name": "CANADA", "iso": "CA", "dial": "+1"},
    "central african republic": {"name": "CENTRAL AFRICAN REPUBLIC", "iso": "CF", "dial": "+236"},
    "chad": {"name": "CHAD", "iso": "TD", "dial": "+235"},
    "chile": {"name": "CHILE", "iso": "CL", "dial": "+56"},
    "china": {"name": "CHINA", "iso": "CN", "dial": "+86"},
    "colombia": {"name": "COLOMBIA", "iso": "CO", "dial": "+57"},
    "comoros": {"name": "COMOROS", "iso": "KM", "dial": "+269"},
    "congo": {"name": "CONGO", "iso": "CG", "dial": "+242"},
    "costa rica": {"name": "COSTA RICA", "iso": "CR", "dial": "+506"},
    "croatia": {"name": "CROATIA", "iso": "HR", "dial": "+385"},
    "cuba": {"name": "CUBA", "iso": "CU", "dial": "+53"},
    "cyprus": {"name": "CYPRUS", "iso": "CY", "dial": "+357"},
    "czech republic": {"name": "CZECH REPUBLIC", "iso": "CZ", "dial": "+420"},
    "czechia": {"name": "CZECH REPUBLIC", "iso": "CZ", "dial": "+420"},
    "denmark": {"name": "DENMARK", "iso": "DK", "dial": "+45"},
    "djibouti": {"name": "DJIBOUTI", "iso": "DJ", "dial": "+253"},
    "dominica": {"name": "DOMINICA", "iso": "DM", "dial": "+1767"},
    "dominican republic": {"name": "DOMINICAN REPUBLIC", "iso": "DO", "dial": "+1809"},
    "dr congo": {"name": "DR CONGO", "iso": "CD", "dial": "+243"},
    "east timor": {"name": "EAST TIMOR", "iso": "TL", "dial": "+670"},
    "ecuador": {"name": "ECUADOR", "iso": "EC", "dial": "+593"},
    "egypt": {"name": "EGYPT", "iso": "EG", "dial": "+20"},
    "el salvador": {"name": "EL SALVADOR", "iso": "SV", "dial": "+503"},
    "equatorial guinea": {"name": "EQUATORIAL GUINEA", "iso": "GQ", "dial": "+240"},
    "eritrea": {"name": "ERITREA", "iso": "ER", "dial": "+291"},
    "estonia": {"name": "ESTONIA", "iso": "EE", "dial": "+372"},
    "eswatini": {"name": "ESWATINI", "iso": "SZ", "dial": "+268"},
    "ethiopia": {"name": "ETHIOPIA", "iso": "ET", "dial": "+251"},
    "fiji": {"name": "FIJI", "iso": "FJ", "dial": "+679"},
    "finland": {"name": "FINLAND", "iso": "FI", "dial": "+358"},
    "france": {"name": "FRANCE", "iso": "FR", "dial": "+33"},
    "gabon": {"name": "GABON", "iso": "GA", "dial": "+241"},
    "gambia": {"name": "GAMBIA", "iso": "GM", "dial": "+220"},
    "georgia": {"name": "GEORGIA", "iso": "GE", "dial": "+995"},
    "germany": {"name": "GERMANY", "iso": "DE", "dial": "+49"},
    "ghana": {"name": "GHANA", "iso": "GH", "dial": "+233"},
    "greece": {"name": "GREECE", "iso": "GR", "dial": "+30"},
    "grenada": {"name": "GRENADA", "iso": "GD", "dial": "+1473"},
    "guatemala": {"name": "GUATEMALA", "iso": "GT", "dial": "+502"},
    "guinea": {"name": "GUINEA", "iso": "GN", "dial": "+224"},
    "guinea-bissau": {"name": "GUINEA-BISSAU", "iso": "GW", "dial": "+245"},
    "guyana": {"name": "GUYANA", "iso": "GY", "dial": "+592"},
    "haiti": {"name": "HAITI", "iso": "HT", "dial": "+509"},
    "honduras": {"name": "HONDURAS", "iso": "HN", "dial": "+504"},
    "hungary": {"name": "HUNGARY", "iso": "HU", "dial": "+36"},
    "iceland": {"name": "ICELAND", "iso": "IS", "dial": "+354"},
    "india": {"name": "INDIA", "iso": "IN", "dial": "+91"},
    "indonesia": {"name": "INDONESIA", "iso": "ID", "dial": "+62"},
    "iran": {"name": "IRAN", "iso": "IR", "dial": "+98"},
    "iraq": {"name": "IRAQ", "iso": "IQ", "dial": "+964"},
    "ireland": {"name": "IRELAND", "iso": "IE", "dial": "+353"},
    "israel": {"name": "ISRAEL", "iso": "IL", "dial": "+972"},
    "italy": {"name": "ITALY", "iso": "IT", "dial": "+39"},
    "ivory coast": {"name": "IVORY COAST", "iso": "CI", "dial": "+225"},
    "jamaica": {"name": "JAMAICA", "iso": "JM", "dial": "+1876"},
    "japan": {"name": "JAPAN", "iso": "JP", "dial": "+81"},
    "jordan": {"name": "JORDAN", "iso": "JO", "dial": "+962"},
    "kazakhstan": {"name": "KAZAKHSTAN", "iso": "KZ", "dial": "+7"},
    "kenya": {"name": "KENYA", "iso": "KE", "dial": "+254"},
    "kiribati": {"name": "KIRIBATI", "iso": "KI", "dial": "+686"},
    "kuwait": {"name": "KUWAIT", "iso": "KW", "dial": "+965"},
    "kyrgyzstan": {"name": "KYRGYZSTAN", "iso": "KG", "dial": "+996"},
    "laos": {"name": "LAOS", "iso": "LA", "dial": "+856"},
    "latvia": {"name": "LATVIA", "iso": "LV", "dial": "+371"},
    "lebanon": {"name": "LEBANON", "iso": "LB", "dial": "+961"},
    "lesotho": {"name": "LESOTHO", "iso": "LS", "dial": "+266"},
    "liberia": {"name": "LIBERIA", "iso": "LR", "dial": "+231"},
    "libya": {"name": "LIBYA", "iso": "LY", "dial": "+218"},
    "liechtenstein": {"name": "LIECHTENSTEIN", "iso": "LI", "dial": "+423"},
    "lithuania": {"name": "LITHUANIA", "iso": "LT", "dial": "+370"},
    "luxembourg": {"name": "LUXEMBOURG", "iso": "LU", "dial": "+352"},
    "madagascar": {"name": "MADAGASCAR", "iso": "MG", "dial": "+261"},
    "malawi": {"name": "MALAWI", "iso": "MW", "dial": "+265"},
    "malaysia": {"name": "MALAYSIA", "iso": "MY", "dial": "+60"},
    "maldives": {"name": "MALDIVES", "iso": "MV", "dial": "+960"},
    "mali": {"name": "MALI", "iso": "ML", "dial": "+223"},
    "malta": {"name": "MALTA", "iso": "MT", "dial": "+356"},
    "marshall islands": {"name": "MARSHALL ISLANDS", "iso": "MH", "dial": "+692"},
    "mauritania": {"name": "MAURITANIA", "iso": "MR", "dial": "+222"},
    "mauritius": {"name": "MAURITIUS", "iso": "MU", "dial": "+230"},
    "mexico": {"name": "MEXICO", "iso": "MX", "dial": "+52"},
    "micronesia": {"name": "MICRONESIA", "iso": "FM", "dial": "+691"},
    "moldova": {"name": "MOLDOVA", "iso": "MD", "dial": "+373"},
    "monaco": {"name": "MONACO", "iso": "MC", "dial": "+377"},
    "mongolia": {"name": "MONGOLIA", "iso": "MN", "dial": "+976"},
    "montenegro": {"name": "MONTENEGRO", "iso": "ME", "dial": "+382"},
    "morocco": {"name": "MOROCCO", "iso": "MA", "dial": "+212"},
    "mozambique": {"name": "MOZAMBIQUE", "iso": "MZ", "dial": "+258"},
    "myanmar": {"name": "MYANMAR", "iso": "MM", "dial": "+95"},
    "namibia": {"name": "NAMIBIA", "iso": "NA", "dial": "+264"},
    "nauru": {"name": "NAURU", "iso": "NR", "dial": "+674"},
    "nepal": {"name": "NEPAL", "iso": "NP", "dial": "+977"},
    "netherlands": {"name": "NETHERLANDS", "iso": "NL", "dial": "+31"},
    "new zealand": {"name": "NEW ZEALAND", "iso": "NZ", "dial": "+64"},
    "nicaragua": {"name": "NICARAGUA", "iso": "NI", "dial": "+505"},
    "niger": {"name": "NIGER", "iso": "NE", "dial": "+227"},
    "nigeria": {"name": "NIGERIA", "iso": "NG", "dial": "+234"},
    "north korea": {"name": "NORTH KOREA", "iso": "KP", "dial": "+850"},
    "north macedonia": {"name": "NORTH MACEDONIA", "iso": "MK", "dial": "+389"},
    "norway": {"name": "NORWAY", "iso": "NO", "dial": "+47"},
    "oman": {"name": "OMAN", "iso": "OM", "dial": "+968"},
    "pakistan": {"name": "PAKISTAN", "iso": "PK", "dial": "+92"},
    "palau": {"name": "PALAU", "iso": "PW", "dial": "+680"},
    "palestine": {"name": "PALESTINE", "iso": "PS", "dial": "+970"},
    "panama": {"name": "PANAMA", "iso": "PA", "dial": "+507"},
    "papua new guinea": {"name": "PAPUA NEW GUINEA", "iso": "PG", "dial": "+675"},
    "paraguay": {"name": "PARAGUAY", "iso": "PY", "dial": "+595"},
    "peru": {"name": "PERU", "iso": "PE", "dial": "+51"},
    "philippines": {"name": "PHILIPPINES", "iso": "PH", "dial": "+63"},
    "poland": {"name": "POLAND", "iso": "PL", "dial": "+48"},
    "portugal": {"name": "PORTUGAL", "iso": "PT", "dial": "+351"},
    "qatar": {"name": "QATAR", "iso": "QA", "dial": "+974"},
    "romania": {"name": "ROMANIA", "iso": "RO", "dial": "+40"},
    "russia": {"name": "RUSSIA", "iso": "RU", "dial": "+7"},
    "rwanda": {"name": "RWANDA", "iso": "RW", "dial": "+250"},
    "saint kitts and nevis": {"name": "SAINT KITTS AND NEVIS", "iso": "KN", "dial": "+1869"},
    "saint lucia": {"name": "SAINT LUCIA", "iso": "LC", "dial": "+1758"},
    "saint vincent": {"name": "SAINT VINCENT", "iso": "VC", "dial": "+1784"},
    "samoa": {"name": "SAMOA", "iso": "WS", "dial": "+685"},
    "san marino": {"name": "SAN MARINO", "iso": "SM", "dial": "+378"},
    "sao tome and principe": {"name": "SAO TOME AND PRINCIPE", "iso": "ST", "dial": "+239"},
    "saudi arabia": {"name": "SAUDI ARABIA", "iso": "SA", "dial": "+966"},
    "senegal": {"name": "SENEGAL", "iso": "SN", "dial": "+221"},
    "serbia": {"name": "SERBIA", "iso": "RS", "dial": "+381"},
    "seychelles": {"name": "SEYCHELLES", "iso": "SC", "dial": "+248"},
    "sierra leone": {"name": "SIERRA LEONE", "iso": "SL", "dial": "+232"},
    "singapore": {"name": "SINGAPORE", "iso": "SG", "dial": "+65"},
    "slovakia": {"name": "SLOVAKIA", "iso": "SK", "dial": "+421"},
    "slovenia": {"name": "SLOVENIA", "iso": "SI", "dial": "+386"},
    "solomon islands": {"name": "SOLOMON ISLANDS", "iso": "SB", "dial": "+677"},
    "somalia": {"name": "SOMALIA", "iso": "SO", "dial": "+252"},
    "south africa": {"name": "SOUTH AFRICA", "iso": "ZA", "dial": "+27"},
    "south korea": {"name": "SOUTH KOREA", "iso": "KR", "dial": "+82"},
    "south sudan": {"name": "SOUTH SUDAN", "iso": "SS", "dial": "+211"},
    "spain": {"name": "SPAIN", "iso": "ES", "dial": "+34"},
    "sri lanka": {"name": "SRI LANKA", "iso": "LK", "dial": "+94"},
    "sudan": {"name": "SUDAN", "iso": "SD", "dial": "+249"},
    "suriname": {"name": "SURINAME", "iso": "SR", "dial": "+597"},
    "sweden": {"name": "SWEDEN", "iso": "SE", "dial": "+46"},
    "switzerland": {"name": "SWITZERLAND", "iso": "CH", "dial": "+41"},
    "syria": {"name": "SYRIA", "iso": "SY", "dial": "+963"},
    "taiwan": {"name": "TAIWAN", "iso": "TW", "dial": "+886"},
    "tajikistan": {"name": "TAJIKISTAN", "iso": "TJ", "dial": "+992"},
    "tanzania": {"name": "TANZANIA", "iso": "TZ", "dial": "+255"},
    "thailand": {"name": "THAILAND", "iso": "TH", "dial": "+66"},
    "togo": {"name": "TOGO", "iso": "TG", "dial": "+228"},
    "tonga": {"name": "TONGA", "iso": "TO", "dial": "+676"},
    "trinidad and tobago": {"name": "TRINIDAD AND TOBAGO", "iso": "TT", "dial": "+1868"},
    "tunisia": {"name": "TUNISIA", "iso": "TN", "dial": "+216"},
    "turkey": {"name": "TURKEY", "iso": "TR", "dial": "+90"},
    "turkmenistan": {"name": "TURKMENISTAN", "iso": "TM", "dial": "+993"},
    "tuvalu": {"name": "TUVALU", "iso": "TV", "dial": "+688"},
    "uganda": {"name": "UGANDA", "iso": "UG", "dial": "+256"},
    "ukraine": {"name": "UKRAINE", "iso": "UA", "dial": "+380"},
    "united arab emirates": {"name": "UNITED ARAB EMIRATES", "iso": "AE", "dial": "+971"},
    "united kingdom": {"name": "UNITED KINGDOM", "iso": "GB", "dial": "+44"},
    "united states": {"name": "UNITED STATES", "iso": "US", "dial": "+1"},
    "uruguay": {"name": "URUGUAY", "iso": "UY", "dial": "+598"},
    "uzbekistan": {"name": "UZBEKISTAN", "iso": "UZ", "dial": "+998"},
    "vanuatu": {"name": "VANUATU", "iso": "VU", "dial": "+678"},
    "vatican city": {"name": "VATICAN CITY", "iso": "VA", "dial": "+379"},
    "venezuela": {"name": "VENEZUELA", "iso": "VE", "dial": "+58"},
    "vietnam": {"name": "VIETNAM", "iso": "VN", "dial": "+84"},
    "yemen": {"name": "YEMEN", "iso": "YE", "dial": "+967"},
    "zambia": {"name": "ZAMBIA", "iso": "ZM", "dial": "+260"},
    "zimbabwe": {"name": "ZIMBABWE", "iso": "ZW", "dial": "+263"},
}

# Disambiguates shared dial codes (e.g. +7 covers RU and KZ).
PREFIX_TO_ISO: dict[tuple[str, str], str] = {
    ("+7", "9"): "RU",
    ("+7", "7"): "KZ",
}

GLOBE = "\U0001F310"


# ────────────────────────────────────────────────────────────────────
# Country / flag helpers
# ────────────────────────────────────────────────────────────────────
def country_flag(iso_code: str) -> str:
    """Convert 2-letter ISO code to flag emoji."""
    iso_code = (iso_code or "").upper().strip()
    if len(iso_code) != 2 or not iso_code.isalpha():
        return GLOBE
    return chr(0x1F1E6 + ord(iso_code[0]) - ord("A")) + chr(
        0x1F1E6 + ord(iso_code[1]) - ord("A")
    )


def _find_iso_by_prefix(dial_code: str, prefix: str | None = None
                        ) -> tuple[str | None, str]:
    """Look up ISO code + flag using prefix-aware matching.
    Logic kept identical to main122.py.
    """
    if prefix:
        for (tbl_dial, tbl_pfx), tbl_iso in PREFIX_TO_ISO.items():
            if dial_code == tbl_dial and prefix.startswith(tbl_pfx):
                return tbl_iso, country_flag(tbl_iso)

        composite = dial_code + prefix
        best_iso, best_len = None, 0
        for _key, data in COUNTRY_DB.items():
            db_dial = data["dial"]
            if db_dial == composite:
                return data["iso"], country_flag(data["iso"])
            if composite.startswith(db_dial) and len(db_dial) > best_len:
                best_iso, best_len = data["iso"], len(db_dial)
            elif db_dial.startswith(composite) and len(db_dial) > best_len:
                best_iso, best_len = data["iso"], len(db_dial)
        if best_iso:
            return best_iso, country_flag(best_iso)

    for _key, data in COUNTRY_DB.items():
        if data["dial"] == dial_code:
            return data["iso"], country_flag(data["iso"])

    for (tbl_dial, tbl_pfx), tbl_iso in PREFIX_TO_ISO.items():
        check = tbl_dial + tbl_pfx
        if dial_code.startswith(check):
            return tbl_iso, country_flag(tbl_iso)

    best_iso, best_len = None, 0
    for _key, data in COUNTRY_DB.items():
        db_dial = data["dial"]
        if dial_code.startswith(db_dial) and len(db_dial) > best_len:
            best_iso, best_len = data["iso"], len(db_dial)
    if best_iso:
        return best_iso, country_flag(best_iso)

    return None, GLOBE


_SERVICE_TOKEN_RE = re.compile(
    r"^(WS|TG|FB|IG|MS|G|APPLE|DISCORD|SIGNAL|SNAPCHAT|TIKTOK|TINDER|"
    r"CHATGPT|VIBER|WHATSAPP|TELEGRAM|FACEBOOK|INSTAGRAM|MICROSOFT|GOOGLE|"
    r"GMAIL)$",
    re.IGNORECASE,
)

# Friendly long-form → canonical short-form mapping.
_SERVICE_NORMALISE = {
    "WHATSAPP": "WS",
    "TELEGRAM": "TG",
    "FACEBOOK": "FB",
    "INSTAGRAM": "IG",
    "MICROSOFT": "MS",
    "GOOGLE": "G",
    "GMAIL": "G",
}


def _canon_service(token: str | None) -> str | None:
    if not token:
        return None
    t = token.strip().upper()
    if not t:
        return None
    return _SERVICE_NORMALISE.get(t, t)


def parse_country_input(text: str):
    """Parse admin input.  Accepts (in any order):

      INDIA +91
      INDIA +91 WS
      INDIA WS +91
      RUSSIA +7 9
      RUSSIA +7 9 WS
      RUSSIA WS +7 9
      INDIA +91 WHATSAPP

    Returns (storage_key, display_name, iso, dial_code, prefix, flag,
    service) or (None,)*7 on failure.

    Service is the new optional last token (canonicalised to a short
    code: WS / TG / FB / IG / MS / G / APPLE / DISCORD / SIGNAL /
    SNAPCHAT / TIKTOK / TINDER / CHATGPT / VIBER).
    """
    text = (text or "").strip()
    if not text:
        return None, None, None, None, None, None, None

    # Tokenise on whitespace; service / prefix / dial are 1-token each.
    parts = text.split()
    if len(parts) < 2:
        return None, None, None, None, None, None, None

    # ── Pull out a service token if present ────────────────────────
    service: str | None = None
    if _SERVICE_TOKEN_RE.match(parts[-1]):
        service = parts.pop()
    elif len(parts) >= 3 and _SERVICE_TOKEN_RE.match(parts[-2]) \
            and parts[-1].lstrip("+").isdigit():
        # 'INDIA WS +91 9' would put the service in [-3] — handled in
        # the alternative split below.  This branch handles plain
        # 'INDIA WS +91'.
        pass

    # Look for a service token sitting BEFORE the dial code (e.g.
    # 'INDIA WS +91' or 'INDIA WS +7 9').
    if service is None:
        for i in range(len(parts) - 1, 0, -1):
            if _SERVICE_TOKEN_RE.match(parts[i]) \
                    and any(p.startswith("+") or p.lstrip().lstrip("+").isdigit()
                            for p in parts[i + 1:]):
                service = parts.pop(i)
                break

    # ── Now run the legacy regex on the remaining text ─────────────
    rest = " ".join(parts)
    match = re.match(r"^(.+?)\s+\+?(\d{1,4})(?:\s+(\d{1,10}))?\s*$", rest)
    if not match:
        return None, None, None, None, None, None, None
    display_name = match.group(1).strip()
    dial_digits = match.group(2).strip()
    dial_code = f"+{dial_digits}"
    prefix = match.group(3)
    if prefix:
        prefix = prefix.strip()
    if not display_name:
        return None, None, None, None, None, None, None

    iso, flag = _find_iso_by_prefix(dial_code, prefix)

    safe_name = re.sub(r"[^a-z0-9]+", "_", display_name.lower()).strip("_")
    key_parts = [safe_name, dial_digits]
    if prefix:
        key_parts.append(prefix)
    if service:
        key_parts.append(_canon_service(service).lower())
    storage_key = "_".join(key_parts)
    return (storage_key, display_name, iso, dial_code, prefix, flag,
            _canon_service(service))


def country_stock(c_key: str | None,
                  info: dict | None = None) -> int:
    """Live stock = number of available phone numbers in the pool."""
    if info is None:
        info = db.COUNTRIES["countries"].get(c_key or "", {})
    return len(info.get("numbers") or [])


def stock_indicator(stock: int) -> str:
    """🟢 / 🟡 / 🔴 traffic-light prefix used in stock displays."""
    if stock <= 0:
        return "🔴"
    if stock < 5:
        return "🟡"
    return "🟢"


def stock_button_style(stock: int) -> str | None:
    """Returns aiogram `style` value for take-number buttons."""
    if stock <= 0:
        return "danger"
    if stock < 5:
        return "primary"
    return "success"


def get_country_label(c_key: str, info: dict,
                      *, with_flag: bool = True) -> str:
    """Plain-text label for country buttons.

    `with_flag=False` is used by `country_button` when an
    `icon_custom_emoji_id` is being attached, so the same flag never
    renders twice on Premium clients.
    """
    flag = info.get("flag", GLOBE)
    display = info.get("display_name", c_key.upper())
    dial = info.get("dial_code", "")
    service = (info.get("service") or "").strip().upper()
    stock = country_stock(c_key, info)
    name_block = f"{display}"
    if dial:
        name_block += f" {dial}"
    if service:
        name_block += f" {service}"
    prefix = f"{flag} " if with_flag else ""
    if stock <= 0:
        return f"{prefix}{name_block}"
    if stock < 5:
        return f"{prefix}{name_block} · {stock}"
    return f"{prefix}{name_block} · {stock}"


def country_button(c_key: str, info: dict,
                   *, callback_data: str | None = None
                   ) -> InlineKeyboardButton:
    """Premium country button — `icon_custom_emoji_id` carries the
    country flag, the text label carries name + dial + service +
    stock.  When the icon is honoured the flag renders once (from
    the icon); when it isn't, we fall back to a Unicode flag in the
    text so non-Premium clients still see one.
    """
    iso = info.get("iso") or ""
    service = (info.get("service") or "").strip().upper()
    stock = country_stock(c_key, info)

    # Prefer the country flag custom emoji; fall back to service emoji
    # only if the flag is missing.  This keeps the country
    # immediately recognisable.
    icon_id = emojis.country_emoji_id(iso) or emojis.service_emoji_id(service)

    # Drop the Unicode flag from the text when we have a premium
    # icon — otherwise Premium clients render the flag twice.
    text_label = get_country_label(c_key, info, with_flag=not icon_id)
    style = stock_button_style(stock)

    return InlineKeyboardButton(
        text=text_label,
        callback_data=callback_data or f"take_{c_key}",
        icon_custom_emoji_id=icon_id,
        style=style,
    )


def country_emoji_id(iso: str | None) -> str | None:
    return emojis.country_emoji_id(iso)


def service_emoji_id(service: str | None) -> str | None:
    return emojis.service_emoji_id(service)


def country_flag_from_key(c_key: str) -> str:
    info = db.COUNTRIES["countries"].get(c_key, {})
    return info.get("flag") or GLOBE


def country_display_from_key(c_key: str) -> str:
    info = db.COUNTRIES["countries"].get(c_key, {})
    return info.get("display_name") or c_key.upper()


# ────────────────────────────────────────────────────────────────────
# OTP detection — smarter, more tolerant version of main122.py.
# Detects WhatsApp / Telegram / Google / numeric / hyphenated /
# multiline / mixed formats. Normalises to NFKC and strips invisible
# unicode controls before matching.
# ────────────────────────────────────────────────────────────────────
INVISIBLE_RE = re.compile(
    "["
    "\u200b\u200c\u200d\u200e\u200f"
    "\u2060\u2061\u2062\u2063\u2064"
    "\ufeff"
    "]"
)

# OTP keywords used by Strategy 1.  Wide net: multiple languages /
# services / wordings.  Order does not matter — we only look for a
# match anywhere in the cleaned text.
_OTP_KEYWORDS = (
    r"OTP|Code|Codigo|Código|Codigo de verificación|Pass\s*code|Passcode|"
    r"Verification(?:\s+code)?|Confirm(?:ation)?(?:\s+code)?|Auth(?:entication)?\s+code|"
    r"Security\s+code|Login\s+code|PIN|TAN|"
    r"WhatsApp\s+code|Telegram\s+code|Google\s+code"
)
# Keyword-context regexes are deliberately loose: when a keyword is
# right next to the digits, even single-digit-with-space patterns are
# accepted (e.g. "Code: 8 8 7 0 9 5").  We tolerate filler words like
# "is", "=", "your" between the keyword and the digits, but we DO NOT
# allow the digit group to cross a newline — that's what produced
# false matches that merged the OTP with the phone number on the
# next line.
_KEYWORD_NEAR_OTP = re.compile(
    rf"(?:{_OTP_KEYWORDS})"
    r"(?:\s+(?:is|are|=|为|是))?(?:\s+(?:your|the))?"
    r"[\s:：\-]*"                                        # may cross a newline
    r"((?:\d[ \t\-]?){3,11}\d)",                        # digit group: NO newline
    re.IGNORECASE,
)
_OTP_NEAR_KEYWORD = re.compile(
    r"((?:\d[ \t\-]?){3,11}\d)"                         # digit group: NO newline
    r"\s*(?:is\s+your|为您的|是您的|verification|confirmation|auth(?:entication)?|"
    r"login|security|otp|code|pin|passcode)",
    re.IGNORECASE,
)
# Strategy-3 candidates are stricter to avoid false positives on
# free-form text (no keyword context to lean on).
_PLAIN_HYPHEN_OTP = re.compile(r"\b\d{2,4}(?:-\d{2,4}){1,3}\b")
_PLAIN_NUMERIC_OTP = re.compile(r"(?<!\d)\d{4,8}(?!\d)")
_PHONE_RE = re.compile(r"\+?\d[\d\s\-().]{4,25}\d")

_YEAR_RE = re.compile(r"^(?:19|20)\d{2}$")


def normalize_text(text: str) -> str:
    """NFKC + strip invisible chars + collapse whitespace inside the line."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = INVISIBLE_RE.sub("", text)
    return text


def _normalize_otp(raw: str, *, allow_year: bool = True) -> str | None:
    """Strip separators inside an OTP candidate.

    ``allow_year`` is True for keyword-context strategies (we trust
    the keyword) and False for plain-numeric strategy 3 (where a bare
    "2025" is almost never an OTP).
    """
    if not raw:
        return None
    digits = re.sub(r"[\s\-]", "", raw)
    if not digits.isdigit():
        return None
    if len(digits) < 4 or len(digits) > 10:
        return None
    if not allow_year and _YEAR_RE.match(digits):
        return None
    return digits


def _format_otp_for_display(raw: str) -> str:
    """Keep the user-facing pretty form (preserve hyphen if present)."""
    raw = raw.strip()
    raw = re.sub(r"\s+", "-", raw) if "-" in raw else raw.replace(" ", "")
    return raw


def normalize_phone(num: str) -> str:
    """Strip every non-digit so phone-number comparisons are stable."""
    return re.sub(r"\D", "", str(num or ""))


def parse_otp(text: str) -> tuple[str | None, str | None, str | None]:
    """Extract (number, otp_digits, otp_pretty) from a free-form group message.

    Returns (None, None, None) when nothing plausible is found.

    `otp_digits` is the version we use for matching / persistence
    (digits only); `otp_pretty` keeps the original hyphenated form
    where applicable (e.g. "607-239") for display.
    """
    text = normalize_text(text)
    if not text:
        return None, None, None

    # Pre-extract phone digits so we can avoid matching OTP candidates
    # that are actually fragments of the phone number (e.g. "123-4567"
    # in "+1 (555) 123-4567").
    phone_digits_set: set[str] = set()
    for line in text.splitlines():
        for pm in _PHONE_RE.finditer(line):
            pd = re.sub(r"\D", "", pm.group(0))
            if len(pd) >= 7:
                phone_digits_set.add(pd)

    def _is_phone_fragment(otp_digits: str) -> bool:
        return any(otp_digits in pd and len(otp_digits) >= 6
                   for pd in phone_digits_set)

    # ── Strategy 1: keyword → code ───────────────────────────────
    raw_otp = None
    keyword_context = False
    m = _KEYWORD_NEAR_OTP.search(text)
    if m:
        raw_otp = m.group(1)
        keyword_context = True

    # ── Strategy 2: code → keyword ───────────────────────────────
    if not raw_otp:
        m = _OTP_NEAR_KEYWORD.search(text)
        if m:
            raw_otp = m.group(1)
            keyword_context = True

    # ── Strategy 3a: hyphenated form (e.g. "607-239" / "12-34-56") ──
    if not raw_otp:
        for cand in _PLAIN_HYPHEN_OTP.findall(text):
            digits = re.sub(r"[\s\-]", "", cand)
            if not digits.isdigit():
                continue
            if _YEAR_RE.match(digits):
                continue
            if _is_phone_fragment(digits):
                continue
            if 4 <= len(digits) <= 10:
                raw_otp = cand
                break

    # ── Strategy 3b: plain 4-8 digit token, not adjacent to other digits ──
    if not raw_otp:
        candidates = _PLAIN_NUMERIC_OTP.findall(text)
        plausible = [c for c in candidates
                     if not _YEAR_RE.match(c)
                     and 4 <= len(c) <= 8
                     and not _is_phone_fragment(c)]
        if len(plausible) == 1:
            raw_otp = plausible[0]
        elif len(plausible) > 1:
            short = [c for c in plausible if 4 <= len(c) <= 7]
            if len(short) == 1:
                raw_otp = short[0]

    if not raw_otp:
        return None, None, None

    otp_digits = _normalize_otp(raw_otp, allow_year=keyword_context)
    if not otp_digits:
        return None, None, None
    otp_pretty = _format_otp_for_display(raw_otp)

    # ── Phone number — accept international and prefixed formats ─
    # Two-pass strategy:
    #   pass 1: only consider lines that look like the phone-number
    #           field ("Number: …", "Phone: …", or a bare "+…" line),
    #           and explicitly skip Time/Date/Code/OTP/etc lines.
    #           This stops timestamps like "2026-05-09 18:27:09" from
    #           being captured as a phone number.
    #   pass 2: fall back to "first phone-shaped match anywhere" so
    #           messages without explicit labels still work.
    _LABEL_RE = re.compile(
        r"^\s*(?:number|phone|mobile|tel|to|recipient)\s*[:\-]",
        re.IGNORECASE,
    )
    _SKIP_RE = re.compile(
        r"^\s*(?:time|date|service|country|otp|code|pin|verification|"
        r"confirmation|auth(?:entication)?|login|security|message)\s*[:\-]",
        re.IGNORECASE,
    )

    def _accept(candidate_raw: str) -> str | None:
        candidate = re.sub(r"[\s().\-]", "", candidate_raw)
        digits_only = re.sub(r"\D", "", candidate)
        if len(digits_only) < 7 or digits_only == otp_digits:
            return None
        return candidate

    number: str | None = None
    for line in text.splitlines():
        if _SKIP_RE.match(line):
            continue
        is_labelled = bool(_LABEL_RE.match(line))
        is_plus_prefixed = line.lstrip().startswith("+")
        if not (is_labelled or is_plus_prefixed):
            continue
        m = _PHONE_RE.search(line)
        if not m:
            continue
        candidate = _accept(m.group(0))
        if candidate:
            number = candidate
            break

    if not number:
        # Pass 2a: stricter regex requiring an explicit '+' country
        # code.  This bypasses the SKIP filter — letting one-liners
        # like 'OTP: 123-456 from +1234567890' still match — without
        # mistakenly catching timestamps such as '2026-05-09 18:27:09'
        # which lack a leading '+'.
        plus_phone_re = re.compile(r"\+\d[\d\s\-().]{4,25}\d")
        for line in text.splitlines():
            for m in plus_phone_re.finditer(line):
                candidate = _accept(m.group(0))
                if candidate:
                    number = candidate
                    break
            if number:
                break

    if not number:
        return None, otp_digits, otp_pretty

    return number, otp_digits, otp_pretty


# ────────────────────────────────────────────────────────────────────
# OTP delivery message — premium HTML format with custom emojis.
# Custom emojis only render when the bot account has Telegram Premium;
# Unicode fallbacks make the message look right regardless.
# ────────────────────────────────────────────────────────────────────
def build_otp_user_message(
    *,
    country_label: str = "",
    number: str,
    otp_pretty: str,
    payout_on: bool,
    price: float,
    new_balance: float,
    iso: str | None = None,
    service: str | None = None,
    country_display: str | None = None,
) -> str:
    """Premium 'OTP Received' card — minimal layout per spec.

    Format:
        ✅ OTP Received!

        🌍 Country: 🇪🇬 Egypt
        📞 Number: +201253754099
        💵 Earned: +0.01 rs
        💰 Balance: 0.03 rs
        ━━━━━━━━━━━━━━━

    Time / Service / extra separators / Reuse button — all removed.
    """
    flag_html = emojis.country_emoji_html(iso,
                                          country_flag(iso) if iso else GLOBE)
    display = country_display or country_label or "Unknown"

    earnings_block = ""
    if payout_on:
        earnings_block = (
            f"\n💵 Earned: +{price} rs"
            f"\n💰 Balance: {new_balance} rs"
        )

    return (
        "✅ <b>OTP Received!</b>\n\n"
        f"🌍 Country: {flag_html} {display}\n"
        f"📞 Number: <code>{number}</code>"
        f"{earnings_block}\n"
        "━━━━━━━━━━━━━━━"
    )


def build_active_number_panel(
    *,
    country_key: str | None,
    info: dict | None,
    number: str,
    numbers_extra: list[str] | None = None,
) -> str:
    """Premium 'Active Number' panel — minimal layout per spec.

    Format:
        ━━━━━━━━━━━━━━
        📲 Active Number

        🌍 Country: 🇪🇬 Egypt +20

        📞 Left Stock : 5
        ⏳ Status: Waiting OTP…
    """
    info = info or {}
    iso = info.get("iso") or ""
    flag_html = emojis.country_emoji_html(iso, info.get("flag") or GLOBE)
    display = info.get("display_name") or (country_key or "Unknown").upper()
    dial = info.get("dial_code") or ""
    stock = country_stock(country_key, info)
    return (
        "━━━━━━━━━━━━━━\n"
        "📲 <b>Active Number</b>\n\n"
        f"🌍 Country: {flag_html} {display} {dial}\n\n"
        f"📞 Left Stock : <b>{stock}</b>\n"
        "⏳ Status: <b>Waiting OTP…</b>"
    )


def build_forwarded_otp_text(
    *,
    iso: str | None,
    country_display: str,
    service: str | None,
    number: str,
    otp_digits: str,
    otp_pretty: str | None = None,
) -> str:
    """Premium 'Forwarded OTP' card used for the admin/log forwarding."""
    flag_html = emojis.country_emoji_html(iso, country_flag(iso) if iso else GLOBE)
    s = (service or "").strip().upper()
    service_html = (
        f" {emojis.service_emoji_html(s, s)}"
        if s else ""
    )
    current_time = datetime.datetime.now().strftime("%H:%M:%S")
    return (
        "━━━━━━━━━━━━━━━\n"
        "📨 <b>Incoming OTP</b>\n\n"
        f"🌍 {flag_html} <b>{country_display}</b>{service_html}\n"
        f"📞 <code>{number}</code>\n\n"
        f"🔑 <b>OTP:</b> <code>{otp_pretty or otp_digits}</code>\n"
        f"⏰ <code>{current_time}</code>\n"
        "━━━━━━━━━━━━━━━"
    )


def build_numbers_added_text(
    *,
    country_display: str,
    iso: str | None,
    service: str | None,
    quantity: int,
    type_label: str = "Premium OTP",
) -> str:
    """Premium 'New Numbers Added Successfully' card.

    Used immediately after admin uploads numbers and as the body of
    the optional broadcast.  Renders with custom-emoji flags + service
    icons when the bot account is Telegram Premium.
    """
    flag_html = emojis.country_emoji_html(iso, country_flag(iso) if iso else GLOBE)
    s = (service or "").strip().upper()
    service_html = (
        f" {emojis.service_emoji_html(s, s)}"
        if s else ""
    )
    diamond = emojis.tg_emoji_html(
        emojis.service_emoji_id("DIAMOND"), "💎"
    )
    return (
        f"✅ <b>New Numbers Added Successfully!</b> {diamond}\n\n"
        f"🌍 <b>Country:</b> {country_display} {flag_html}{service_html}\n"
        f"📦 <b>Quantity:</b> <code>{int(quantity)}</code>\n"
        f"💎 <b>Type:</b> <i>{type_label}</i>"
    )


# ────────────────────────────────────────────────────────────────────
# Daily-stats helpers (IST 05:30 business-day rule)
# ────────────────────────────────────────────────────────────────────
RESET_HOUR_IST = 5
RESET_MINUTE_IST = 30
IST = ZoneInfo("Asia/Kolkata")


def _ist_now() -> datetime.datetime:
    return datetime.datetime.now(tz=IST)


def _stats_day_str(dt: datetime.datetime) -> str:
    roll = dt.replace(hour=RESET_HOUR_IST, minute=RESET_MINUTE_IST,
                      second=0, microsecond=0)
    if dt < roll:
        dt = dt - datetime.timedelta(days=1)
    return dt.date().strftime("%Y-%m-%d")


def _today_str() -> str:
    return _stats_day_str(_ist_now())


def _default_today(date_str: str | None = None) -> dict:
    return {
        "date": date_str or _today_str(),
        "total_otps": 0,
        "total_earnings": 0.0,
        "countries": {},
    }


def ensure_today() -> None:
    """Roll over `today` to history when a new business day starts."""
    today = _today_str()
    current = db.DAILY_STATS.get("today") or {}
    if current.get("date") != today:
        stale_date = current.get("date")
        if stale_date:
            db.DAILY_STATS.setdefault("history", {})[stale_date] = {
                "total_otps": current.get("total_otps", 0),
                "total_earnings": round(
                    float(current.get("total_earnings", 0)), 4),
                "countries": dict(current.get("countries", {})),
            }
            db.save_daily_history(stale_date)
        db.DAILY_STATS["today"] = _default_today(today)
        db.save_daily_today()


def track_daily_otp(country_key: str | None, price: float) -> None:
    """Record one OTP into today's running stats."""
    ensure_today()
    today = db.DAILY_STATS["today"]
    today["total_otps"] = today.get("total_otps", 0) + 1
    today["total_earnings"] = round(
        float(today.get("total_earnings", 0)) + float(price), 4)
    if country_key:
        today.setdefault("countries", {})[country_key] = (
            today["countries"].get(country_key, 0) + 1
        )
    db.save_daily_today()


def do_daily_reset() -> None:
    ensure_today()
    log.warning("Daily stats auto-reset triggered for %s", _today_str())


async def daily_reset_loop() -> None:
    last_reset_date = db.DAILY_STATS.get("_last_reset_date", "")
    ensure_today()
    while True:
        try:
            now_ist = _ist_now()
            today_str = _stats_day_str(now_ist)
            if (
                now_ist.hour == RESET_HOUR_IST
                and now_ist.minute == RESET_MINUTE_IST
                and last_reset_date != today_str
            ):
                do_daily_reset()
                last_reset_date = today_str
                db.save_last_reset_date(today_str)
            ensure_today()
        except Exception as e:                  # noqa: BLE001
            log.error("daily_reset_loop error: %s", e)
        await asyncio.sleep(60)


def parse_date_input(text: str) -> str | None:
    """Accept YYYY-MM-DD or DD-MM-YYYY."""
    text = (text or "").strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", text)
    if m:
        try:
            datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return text
        except ValueError:
            return None
    m = re.match(r"^(\d{2})-(\d{2})-(\d{4})$", text)
    if m:
        try:
            d = datetime.date(int(m.group(3)), int(m.group(2)),
                              int(m.group(1)))
            return d.strftime("%Y-%m-%d")
        except ValueError:
            return None
    return None


def parse_date_range_input(text: str) -> tuple[str | None, str | None]:
    parts = re.split(r"\s+to\s+", (text or "").strip(), flags=re.IGNORECASE)
    if len(parts) != 2:
        return None, None
    start = parse_date_input(parts[0].strip())
    end = parse_date_input(parts[1].strip())
    if not start or not end:
        return None, None
    if start > end:
        start, end = end, start
    return start, end


def format_daily_stats(date_str: str, data: dict) -> str:
    total_otps = data.get("total_otps", 0)
    total_earnings = round(float(data.get("total_earnings", 0)), 2)
    country_counts = data.get("countries", {})
    try:
        d = datetime.date.fromisoformat(date_str)
        pretty_date = d.strftime("%d %b %Y")
    except Exception:                           # noqa: BLE001
        pretty_date = date_str
    txt = (
        f"📊<b>Stats for {pretty_date}</b>\n\n"
        f"📦Total OTPs: <b>{total_otps}</b>\n"
        f"💰Total Earnings: <b>{total_earnings} rs</b>\n"
    )
    if country_counts:
        txt += "\n🌍<b>By Country:</b>\n"
        for c_key, cnt in sorted(country_counts.items(),
                                 key=lambda x: x[1], reverse=True):
            flag = country_flag_from_key(c_key)
            display = country_display_from_key(c_key)
            txt += f"{flag} {display} — <b>{cnt}</b>\n"
    else:
        txt += "\nNo country data recorded.\n"
    return txt


def format_range_stats(start_str: str, end_str: str) -> str:
    try:
        start_d = datetime.date.fromisoformat(start_str)
        end_d = datetime.date.fromisoformat(end_str)
    except ValueError:
        return "❌Invalid date range."
    ensure_today()
    today_str = _today_str()
    agg_otps = 0
    agg_earnings = 0.0
    agg_countries: dict[str, int] = {}
    days_found = 0
    current = start_d
    while current <= end_d:
        ds = current.strftime("%Y-%m-%d")
        if ds == today_str:
            data = db.DAILY_STATS.get("today", {})
        else:
            data = db.DAILY_STATS.get("history", {}).get(ds, {})
        if data:
            days_found += 1
            agg_otps += data.get("total_otps", 0)
            agg_earnings += float(data.get("total_earnings", 0))
            for c_key, cnt in data.get("countries", {}).items():
                agg_countries[c_key] = agg_countries.get(c_key, 0) + cnt
        current += datetime.timedelta(days=1)
    try:
        pretty_start = start_d.strftime("%d %b %Y")
        pretty_end = end_d.strftime("%d %b %Y")
    except Exception:                           # noqa: BLE001
        pretty_start, pretty_end = start_str, end_str
    txt = (
        f"📊<b>Stats from {pretty_start} to {pretty_end}</b>\n\n"
        f"📅Days with data: <b>{days_found}</b>\n"
        f"📦Total OTPs: <b>{agg_otps}</b>\n"
        f"💰Total Earnings: <b>{round(agg_earnings, 2)} rs</b>\n"
    )
    if agg_countries:
        txt += "\n🌍<b>By Country:</b>\n"
        for c_key, cnt in sorted(agg_countries.items(),
                                 key=lambda x: x[1], reverse=True):
            flag = country_flag_from_key(c_key)
            display = country_display_from_key(c_key)
            txt += f"{flag} {display} — <b>{cnt}</b>\n"
    else:
        txt += "\nNo data found for this range.\n"
    return txt


# ────────────────────────────────────────────────────────────────────
# Force-join helpers
# ────────────────────────────────────────────────────────────────────
def chat_id_to_tme(chat_id: int) -> str:
    s = str(abs(int(chat_id)))
    if s.startswith("100"):
        return f"https://t.me/c/{s[3:]}/1"
    return ""


def fj_link_for_join(chat_entry: dict) -> str:
    lnk = chat_entry.get("link", "")
    if lnk:
        if lnk.startswith("http"):
            return lnk
        if lnk.startswith("@"):
            return f"https://t.me/{lnk[1:]}"
        return f"https://t.me/{lnk}"
    cid = chat_entry.get("chat_id")
    if cid:
        return chat_id_to_tme(cid) or "https://t.me/"
    return "https://t.me/"


def fj_owner_panel_text(fj: dict) -> tuple[str, InlineKeyboardMarkup]:
    chats = fj.get("chats", [])
    enabled = fj.get("enabled", False)
    status = "✅Enabled" if enabled else "❌Disabled"
    toggle_label = "🔴Disable Force Join" if enabled else "🟢Enable Force Join"
    text = (
        f"🚫<b>Force Join Manager</b>\n\n"
        f"Status: <b>{status}</b>\n"
        f"Configured chats: <b>{len(chats)}</b>\n"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [_ikbtn("🔗 Set Links", callback_data="fj_set_links"),
         _ikbtn("📡 Scan Bot's Groups", callback_data="fj_scan")],
        [_ikbtn("📋 View Groups", callback_data="fj_view_groups"),
         _ikbtn("🗑 Remove Group", callback_data="fj_remove_menu")],
        [_ikbtn(toggle_label, callback_data="fj_toggle")],
        [_ikbtn("🔙 Back", callback_data="back_admin")],
    ])
    return text, keyboard


# ────────────────────────────────────────────────────────────────────
# Keyboards (aiogram v3 style)
# ────────────────────────────────────────────────────────────────────
def user_keyboard() -> ReplyKeyboardMarkup:
    """Premium user reply keyboard.  `style` colours render on every
    Telegram client (no Premium required); `icon_custom_emoji_id`
    only renders when the bot account has Telegram Premium and the
    recipient's client is recent enough.  Each button's leading
    Unicode emoji is auto-promoted to a custom-emoji icon via
    `_kbtn` (see `UI_EMOJI_IDS` in `main.py`).
    """
    return ReplyKeyboardMarkup(
        keyboard=[
            [_kbtn("📞 Get Number", style="success"),
             _kbtn("🧹 Clear Prefix", style="danger")],
            [_kbtn("💰 My Balance", style="success"),
             _kbtn("💸 Withdraw", style="danger")],
            [_kbtn("📦 Stock Check", style="primary"),
             _kbtn("❓ Help", style="primary")],
        ],
        resize_keyboard=True,
    )


def admin_keyboard(user_id: int | None = None,
                   owner_id: int | None = None) -> ReplyKeyboardMarkup:
    """Admin reply keyboard.  Day-to-day admin actions are visible to
    every admin.  Sensitive owner-only tools (Broadcast, Admin
    Management, Log Forwarding, Force Join) are collapsed under a
    single ``👑 Owner`` button — only the owner sees it.

    Every button's leading emoji is rendered as a Telegram Premium
    custom-emoji icon via `_kbtn` so the keyboard reads as a row of
    animated icons + label on Premium clients.
    """
    rows = [
        [_kbtn("🌍 Add Country", style="success"),
         _kbtn("❌ Remove Country", style="danger")],
        [_kbtn("📋 Manage Numbers", style="primary"),
         _kbtn("📊 Country Stats", style="primary")],
        [_kbtn("🤖 Bot Stats", style="primary"),
         _kbtn("🔄 Toggle Payout", style="primary")],
        [_kbtn("💳 Payouts", style="primary")],
    ]
    if user_id is not None and owner_id is not None and int(user_id) == int(owner_id):
        rows.append([_kbtn("👑 Owner", style="primary")])
    rows.append([_kbtn("👤 User Mode", style="success")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def owner_keyboard() -> ReplyKeyboardMarkup:
    """Sub-menu shown when the owner taps ``👑 Owner``.  Holds the
    high-impact tools (Broadcast / Admin Management / Log Forwarding
    / Force Join / Import / Export Users).
    Tap ``⬅️ Back to Admin`` to return.
    """
    return ReplyKeyboardMarkup(
        keyboard=[
            [_kbtn("📢 Broadcast", style="success"),
             _kbtn("👥 Admin Management", style="primary")],
            [_kbtn("📥 Import Users", style="primary"),
             _kbtn("📤 Export Users", style="primary")],
            [_kbtn("📡 Log Forwarding", style="primary"),
             _kbtn("🚫 Force Join", style="danger")],
            [_kbtn("⬅️ Back to Admin", style="primary")],
        ],
        resize_keyboard=True,
    )


def login_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [_kbtn("👤 User Panel", style="success"),
             _kbtn("🔐 Admin Panel", style="primary")],
        ],
        resize_keyboard=True,
    )


def active_number_buttons(view_url: str,
                          *, current_number: str | None = None,
                          numbers: list[str] | None = None,
                          iso: str | None = None,
                          ) -> InlineKeyboardMarkup:
    """Buttons under the Active Number panel — minimal premium layout.

    Layout:
        [🌍 Change Country (red)] [🔄 Change Number (blue)]
        [👁 View OTP                                (green)]

    Cancel / Back / per-number copy / Backups — all removed per spec.
    """
    rows: list[list[InlineKeyboardButton]] = [
        [
            _ikbtn("🌍 Change Country",
                   callback_data="user_change_country",
                   style="danger"),
            _ikbtn("🔄 Change Number",
                   callback_data="user_change_number",
                   style="primary"),
        ],
        [
            _ikbtn("👁 View OTP",
                   url=view_url,
                   style="success"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


# Back-compat alias — older code in main.py still imports the old name.
def change_number_buttons(view_url: str) -> InlineKeyboardMarkup:
    return active_number_buttons(view_url)


def otp_received_buttons(otp_digits: str | None,
                         *, view_url: str | None = None,
                         service: str | None = None,
                         ) -> InlineKeyboardMarkup:
    """Premium minimal OTP Received buttons.

    Layout:
        [⟨premium service emoji⟩  380680]   ← copies OTP
        [📲 New Number]                     ← blue, callback

    The first button uses `CopyTextButton` so a single tap copies the
    OTP digits with no dialog.  The button TEXT is just the OTP code
    (no "Copy OTP" label).  When the country has a known service key
    (ws / tg / fb / ig / …) a premium custom emoji is attached via
    `icon_custom_emoji_id` — when it doesn't, the button shows the
    OTP code only.  No Unicode service emojis, ever.
    """
    rows: list[list[InlineKeyboardButton]] = []
    if otp_digits:
        kwargs: dict = {
            "text": str(otp_digits),
            "copy_text": CopyTextButton(text=str(otp_digits)),
            "style": "success",
        }
        svc_id = emojis.service_emoji_id(service) if service else None
        if svc_id:
            kwargs["icon_custom_emoji_id"] = svc_id
        rows.append([InlineKeyboardButton(**kwargs)])

    rows.append([
        _ikbtn("📲 New Number",
               callback_data="user_change_number",
               style="primary"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def stock_check_keyboard(page: int = 0,
                         *, page_size: int = 10
                         ) -> tuple[str, InlineKeyboardMarkup]:
    """Returns (text, keyboard) for the Stock Check panel."""
    rows: list[tuple[str, dict]] = sorted(
        db.COUNTRIES["countries"].items(),
        key=lambda x: x[1].get("display_name", x[0].upper()),
    )
    total_pages = max(1, (len(rows) + page_size - 1) // page_size)
    page = max(0, min(page, total_pages - 1))
    start, end = page * page_size, page * page_size + page_size
    visible = rows[start:end]

    body_lines = ["📦 <b>Stock Check</b>", ""]
    if not visible:
        body_lines.append("<i>No countries yet.</i>")
    for c, info in visible:
        if not isinstance(info, dict):
            continue
        flag_html = emojis.country_emoji_html(info.get("iso"),
                                              info.get("flag") or GLOBE)
        service = (info.get("service") or "").strip().upper()
        service_html = (
            emojis.service_emoji_html(service, service)
            if service else ""
        )
        stock = country_stock(c, info)
        ind = stock_indicator(stock)
        display = info.get("display_name", c.upper())
        dial = info.get("dial_code", "")
        line = f"{ind} {flag_html} <b>{display}</b> {dial}"
        if service_html:
            line += f" {service_html}"
        line += f" — <code>{stock}</code>"
        body_lines.append(line)
    body_lines.append("")
    body_lines.append(f"<i>Page {page+1}/{total_pages}</i>")
    text = "\n".join(body_lines)

    nav_row: list[InlineKeyboardButton] = []
    if page > 0:
        nav_row.append(_ikbtn(
            "◀️ Prev",
            callback_data=f"stock_p_{page-1}",
            style="primary",
        ))
    nav_row.append(_ikbtn(
        "🔄 Refresh",
        callback_data=f"stock_p_{page}",
        style="success",
    ))
    if page + 1 < total_pages:
        nav_row.append(_ikbtn(
            "Next ▶️",
            callback_data=f"stock_p_{page+1}",
            style="primary",
        ))
    rows_kb: list[list[InlineKeyboardButton]] = [nav_row, [
        _ikbtn("📞 Get Number",
               callback_data="user_get_number",
               style="success"),
        _ikbtn("⬅️ Back",
               callback_data="back_user",
               style="primary"),
    ]]
    return text, InlineKeyboardMarkup(inline_keyboard=rows_kb)


def force_join_user_text(missing_chats: list[dict]) -> tuple[str, InlineKeyboardMarkup]:
    """Pretty force-join screen for end-users."""
    text = (
        "━━━━━━━━━━━━━━━\n"
        "🚫 <b>Access Restricted</b>\n\n"
        "Join all required channels below to unlock the bot.\n"
        "━━━━━━━━━━━━━━━"
    )
    buttons: list[list[InlineKeyboardButton]] = []
    for i, e in enumerate(missing_chats, start=1):
        label = e.get("button_name") or e.get("title") or f"Join Channel {i}"
        link = fj_link_for_join(e)
        buttons.append([_ikbtn(
            f"📢 {label}",
            url=link,
            style="primary",
        )])
    buttons.append([_ikbtn(
        "✅ Verify Access",
        callback_data="fj_check",
        style="success",
    )])
    return text, InlineKeyboardMarkup(inline_keyboard=buttons)


def manage_country_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_ikbtn("📤 Upload Numbers", callback_data="upload_numbers"),
         _ikbtn("🗑 Clear Numbers", callback_data="clear_numbers")],
        [_ikbtn("💲 Set Price", callback_data="admin_set_price"),
         _ikbtn("👥 Set User Limit", callback_data="admin_set_user_limit")],
        [_ikbtn("📊 Country Performance",
                callback_data="country_performance")],
        [_ikbtn("🔙 Back", callback_data="back_admin")],
    ])


# ────────────────────────────────────────────────────────────────────
# Broadcast engine — async, batched, FloodWait-aware.
# ────────────────────────────────────────────────────────────────────
DEAD_USER_ERRORS = (
    "bot was blocked", "chat not found", "user is deactivated",
    "chat_id is invalid", "bot can't initiate", "user not found",
)


async def _send_broadcast_one(
    bot,
    chat_id: int,
    *,
    payload: dict,
) -> str:
    """Send one broadcast to one user.

    Returns: 'ok' | 'blocked' | 'deleted' | 'invalid' | 'flood'.

    `payload` describes WHAT to send.  Two modes:
      * `mode="text"` — plain text broadcast.  Keys: text, parse_mode,
        reply_markup, disable_web_page_preview.
      * `mode="copy"` — copy a message verbatim from the admin's chat
        (preserves photo / video / animation / document / captions /
        premium emoji entities / inline keyboards).  Keys: from_chat_id,
        message_id, reply_markup.
    """
    try:
        if payload["mode"] == "text":
            await bot.send_message(
                chat_id=chat_id,
                text=payload["text"],
                parse_mode=payload.get("parse_mode"),
                reply_markup=payload.get("reply_markup"),
                disable_web_page_preview=payload.get(
                    "disable_web_page_preview", True),
            )
        else:
            await bot.copy_message(
                chat_id=chat_id,
                from_chat_id=payload["from_chat_id"],
                message_id=payload["message_id"],
                reply_markup=payload.get("reply_markup"),
            )
        return "ok"
    except Exception as exc:                       # noqa: BLE001
        exc_str = str(exc).lower()
        retry_after = getattr(exc, "retry_after", None)
        if retry_after is None:
            m = re.search(r"(?:retry[\s_-]?after|flood[_\s-]?wait)\D+(\d+)",
                          exc_str)
            if m:
                retry_after = int(m.group(1))
        if retry_after:
            log.warning("Broadcast FloodWait %ss for chat %s",
                        retry_after, chat_id)
            await asyncio.sleep(min(int(retry_after) + 1, 120))
            try:
                if payload["mode"] == "text":
                    await bot.send_message(
                        chat_id=chat_id,
                        text=payload["text"],
                        parse_mode=payload.get("parse_mode"),
                        reply_markup=payload.get("reply_markup"),
                        disable_web_page_preview=payload.get(
                            "disable_web_page_preview", True),
                    )
                else:
                    await bot.copy_message(
                        chat_id=chat_id,
                        from_chat_id=payload["from_chat_id"],
                        message_id=payload["message_id"],
                        reply_markup=payload.get("reply_markup"),
                    )
                return "ok"
            except Exception:                       # noqa: BLE001
                return "flood"
        if any(e in exc_str for e in (
            "user is deactivated", "user_deactivated",
            "user not found", "user_not_found", "chat not found",
            "chat_not_found", "peer_id_invalid", "input_user_deactivated",
        )):
            return "deleted"
        if any(e in exc_str for e in DEAD_USER_ERRORS):
            return "blocked"
        return "invalid"


async def run_broadcast(
    bot,
    *,
    progress_msg,
    user_ids: list[int] | None = None,
    text: str | None = None,
    parse_mode: str | None = "HTML",
    reply_markup=None,
    from_chat_id: int | None = None,
    message_id: int | None = None,
    concurrency: int = 100,
    progress_every: float = 1.5,
    sender_admin: int | None = None,
) -> dict:
    """Ultra-fast async broadcast.

    Architecture:
      * One bounded `asyncio.Semaphore(concurrency)` — caps in-flight
        sends so we never trigger Telegram's global flood guard.
      * Workers run via `asyncio.gather`, kicked off from a single
        producer that *streams* user_ids from PostgreSQL via a
        server-side cursor — the full user list never needs to live
        in RAM.
      * Progress edits happen on a separate timer task (every
        ~`progress_every` s) — so the per-send loop never blocks on
        Telegram edits.
      * Dead users (blocked / deleted / deactivated) are pruned from
        `db.USERS` and from `users` in PostgreSQL in batches of 200.
      * Bot stays fully responsive: every send runs in its own task,
        no sleeps in the hot path, no batch-wide barriers.

    Modes:
      - text broadcast: pass `text` (and optionally `reply_markup`).
      - media broadcast: pass `from_chat_id` + `message_id`.  The
        message is copied verbatim with `bot.copy_message`, preserving
        photo / video / animation / document / caption / premium-emoji
        entities / inline keyboards.

    `user_ids=None` means "stream all users from the DB" — recommended
    so we never load the whole table into RAM.

    Returns a stats dict.
    """
    is_text = text is not None
    if is_text:
        payload: dict = {
            "mode": "text",
            "text": text,
            "parse_mode": parse_mode,
            "reply_markup": reply_markup,
            "disable_web_page_preview": True,
        }
    else:
        if from_chat_id is None or message_id is None:
            raise ValueError(
                "run_broadcast: either `text` OR "
                "(`from_chat_id` + `message_id`) is required.")
        payload = {
            "mode": "copy",
            "from_chat_id": from_chat_id,
            "message_id": message_id,
            "reply_markup": reply_markup,
        }

    sem = asyncio.Semaphore(max(1, int(concurrency)))
    stats = {
        "total":     0,
        "sent":      0,
        "ok":        0,
        "blocked":   0,
        "deleted":   0,
        "invalid":   0,
        "flood":     0,
        "started":   time.time(),
    }
    dead_uids: list[int] = []
    dead_lock = asyncio.Lock()

    async def _flush_dead() -> None:
        async with dead_lock:
            if not dead_uids:
                return
            chunk = dead_uids[:]
            dead_uids.clear()
        try:
            await db.delete_users(chunk)
        except Exception as e:                      # noqa: BLE001
            log.warning("Dead user prune failed: %s", e)

    async def _worker(uid: int) -> None:
        async with sem:
            r = await _send_broadcast_one(bot, uid, payload=payload)
        if r == "ok":
            stats["ok"] += 1
        elif r == "blocked":
            stats["blocked"] += 1
            dead_uids.append(uid)
        elif r == "deleted":
            stats["deleted"] += 1
            dead_uids.append(uid)
        elif r == "flood":
            stats["flood"] += 1
        else:
            stats["invalid"] += 1
        stats["sent"] += 1

    async def _progress_ticker(stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(stop_event.wait(),
                                       timeout=progress_every)
                break
            except asyncio.TimeoutError:
                pass
            elapsed = max(time.time() - stats["started"], 0.001)
            speed = stats["sent"] / elapsed
            try:
                await progress_msg.edit_text(
                    "<b>📢 Broadcasting…</b>\n\n"
                    f"Sent: <b>{stats['sent']}/{stats['total']}</b>\n"
                    f"✅ Delivered: <b>{stats['ok']}</b>\n"
                    f"❌ Blocked: <b>{stats['blocked']}</b>  "
                    f"🗑 Deleted: <b>{stats['deleted']}</b>\n"
                    f"⚠ Invalid: <b>{stats['invalid']}</b>  "
                    f"🌊 FloodWait: <b>{stats['flood']}</b>\n"
                    f"⚡ Speed: <b>{speed:.1f}</b> msg/s\n"
                    f"⏱ Elapsed: <b>{elapsed:.0f}s</b>",
                    parse_mode="HTML",
                )
            except Exception:                       # noqa: BLE001
                pass

    stop_event = asyncio.Event()
    ticker_task = asyncio.create_task(_progress_ticker(stop_event),
                                      name="bcast-progress")

    workers: list[asyncio.Task] = []

    async def _spawn(uid_int: int) -> None:
        stats["total"] += 1
        workers.append(asyncio.create_task(_worker(uid_int)))
        # Light yield so the event loop picks up other tasks
        # (incoming OTPs, callbacks).  Keeps the bot responsive even
        # when streaming millions of users.
        if stats["total"] % 1000 == 0:
            await _flush_dead()
            await asyncio.sleep(0)

    try:
        if user_ids is not None:
            for uid in user_ids:
                try:
                    await _spawn(int(uid))
                except (TypeError, ValueError):
                    continue
        else:
            async for uid in db.stream_user_ids():
                try:
                    await _spawn(int(uid))
                except (TypeError, ValueError):
                    continue

        if workers:
            await asyncio.gather(*workers, return_exceptions=True)
        await _flush_dead()
    finally:
        stop_event.set()
        try:
            await ticker_task
        except Exception:                           # noqa: BLE001
            pass

    elapsed = max(time.time() - stats["started"], 0.001)
    speed = stats["sent"] / elapsed
    stats["elapsed"] = elapsed
    stats["speed"] = speed

    try:
        await progress_msg.edit_text(
            "<b>📢 Broadcast Finished</b>\n\n"
            f"👥 Total: <b>{stats['total']}</b>\n"
            f"✅ Delivered: <b>{stats['ok']}</b>\n"
            f"❌ Blocked: <b>{stats['blocked']}</b>\n"
            f"🗑 Deleted: <b>{stats['deleted']}</b>\n"
            f"⚠ Invalid: <b>{stats['invalid']}</b>\n"
            f"🌊 FloodWait dropped: <b>{stats['flood']}</b>\n"
            f"⚡ Speed: <b>{speed:.1f}</b> msg/s\n"
            f"⏱ Elapsed: <b>{elapsed:.1f}s</b>",
            parse_mode="HTML",
        )
    except Exception:                               # noqa: BLE001
        pass

    # Persist broadcast stats (best-effort).
    try:
        await db.log_broadcast(
            sender_admin=sender_admin,
            content_type="copy" if from_chat_id else "text",
            content=(text or "")[:8000] if text else None,
            delivered=int(stats.get("ok") or 0),
            blocked=int(stats.get("blocked") or 0),
            deleted=int(stats.get("deleted") or 0),
            invalid=int(stats.get("invalid") or 0),
            flood=int(stats.get("flood") or 0),
            elapsed_seconds=float(elapsed),
        )
    except Exception as e:                           # noqa: BLE001
        log.warning("log_broadcast failed: %s", e)

    return stats


# ────────────────────────────────────────────────────────────────────
# Misc
# ────────────────────────────────────────────────────────────────────
def ensure_user(user_id: str, username: str | None = None) -> dict:
    """Get-or-create the user record (mirrors main122.ensure_user)."""
    u = db.USERS.get(user_id)
    if u is None:
        db.USERS[user_id] = {
            "username": username,
            "balance": 0.0,
            "otps": 0,
            "numbers_taken": [],
            "current_number": None,
            "current_numbers": [],
            "current_country": None,
            "awaiting_otp": False,
        }
        db.save_user(user_id)
        return db.USERS[user_id]

    if username and u.get("username") != username:
        u["username"] = username
        db.save_user(user_id)
    return u


def safe_create_task(coro, *, name: str | None = None,
                     pool: set | None = None) -> asyncio.Task:
    task = asyncio.create_task(coro, name=name)
    if pool is not None:
        pool.add(task)
        task.add_done_callback(pool.discard)
    return task


def append_log_line(path: str, msg: str) -> None:
    """Cheap append-only log mirror — non-blocking via best-effort."""
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:                           # noqa: BLE001
        pass


__all__ = [
    "COUNTRY_DB", "PREFIX_TO_ISO", "GLOBE",
    "country_flag", "_find_iso_by_prefix", "parse_country_input",
    "get_country_label", "country_button",
    "country_stock", "stock_indicator", "stock_button_style",
    "country_flag_from_key", "country_display_from_key",
    "country_emoji_id", "service_emoji_id",
    "normalize_text", "normalize_phone", "parse_otp",
    "build_otp_user_message", "build_active_number_panel",
    "build_forwarded_otp_text",
    "RESET_HOUR_IST", "RESET_MINUTE_IST", "IST",
    "_ist_now", "_stats_day_str", "_today_str", "_default_today",
    "ensure_today", "track_daily_otp", "do_daily_reset",
    "daily_reset_loop", "parse_date_input", "parse_date_range_input",
    "format_daily_stats", "format_range_stats",
    "chat_id_to_tme", "fj_link_for_join", "fj_owner_panel_text",
    "user_keyboard", "admin_keyboard", "owner_keyboard", "login_keyboard",
    "active_number_buttons", "change_number_buttons",
    "otp_received_buttons", "stock_check_keyboard",
    "force_join_user_text", "manage_country_kb",
    "build_numbers_added_text",
    "DEAD_USER_ERRORS", "run_broadcast",
    "ensure_user", "safe_create_task", "append_log_line",
]
