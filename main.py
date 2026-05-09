"""
main.py — High-performance OTP forwarding bot.

Stack:
  * aiogram v3            — bot handlers
  * Pyrogram + TgCrypto   — MTProto user-session group reading
  * aiosqlite             — async persistence (see db.py)
  * fully async pipeline  — burst-traffic safe, no blocking I/O on hot path

Behaviour-preserving rewrite of `main122.py`.  Every user-visible flow
is identical: country system, number assignment, OTP detection,
force-join, admin panel, payouts, broadcast, daily IST stats, file
uploads, callback buttons, multi-chat / topic MTProto reading.
"""

from __future__ import annotations

import asyncio
import datetime
import io
import logging
import os
import re
import sys
import time
from typing import Any

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatMemberStatus, ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import (
    BufferedInputFile, CallbackQuery, ChatMemberUpdated,
    InlineKeyboardButton as _BaseInlineKeyboardButton,
    InlineKeyboardMarkup, Message, ReplyKeyboardMarkup,
)

import core
import emojis
import db


# ────────────────────────────────────────────────────────────────────
# Premium-icon wrapper for InlineKeyboardButton
# ────────────────────────────────────────────────────────────────────
# Every direct ``InlineKeyboardButton(...)`` call inside this file
# routes through this thin wrapper so that the first registered
# Unicode emoji in ``text`` is auto-promoted to the corresponding
# Telegram Premium custom-emoji icon (``icon_custom_emoji_id``).
# Pass ``icon_custom_emoji_id=`` explicitly to override the auto
# lookup, or pass an empty string to suppress it entirely.
def InlineKeyboardButton(*, text: str = "", **kwargs) -> _BaseInlineKeyboardButton:  # noqa: N802
    if "icon_custom_emoji_id" not in kwargs and text:
        eid = emojis.first_emoji_id(text)
        if eid:
            kwargs["icon_custom_emoji_id"] = eid
    return _BaseInlineKeyboardButton(text=text, **kwargs)


# ════════════════════════════════════════════════════════════════════
#                          MASTER CONFIG
# ────────────────────────────────────────────────────────────────────
# All bot configuration lives here as plain Python constants.  Edit
# the values below to point the bot at your bot token, Pyrogram
# user-session, OTP groups and Supabase / PostgreSQL DSN.  No `.env`
# file is read; nothing is pulled from the process environment.
# ════════════════════════════════════════════════════════════════════

# ── Bot ────────────────────────────────────────────────────────────
BOT_TOKEN = "8481958470:AAG3ZI5rrvNiDOWXkifNCKJYoxpbRAmA9Yw"
OWNER_ID  = 5048281046

# ── User-session (MTProto group reader, via Pyrogram) ──────────────
API_ID     = 38785545
API_HASH   = "d5ad8c7bd2b01e837e2deb0b41dee770"
USER_PHONE = "+5351813264"
USER_2FA   = "FILE@123"

# Optional: paste a Pyrogram string session here to skip phone/2FA.
# Generate with:
#   from pyrogram import Client
#   c = Client("gen", API_ID, API_HASH); c.connect();
#   print(c.export_session_string()); c.disconnect()
PYRO_SESSION = ""

# ── OTP groups ─────────────────────────────────────────────────────
# Each entry: {"chat_id": <int>, "topic_id": <int | None>}.
#
#   topic_id  → behaviour
#   ──────────┼──────────────────────────────────────────────────────
#    None     │ read EVERY message in the whole chat (no topic filter)
#    1        │ General topic only (forum chats; Pyrogram reports
#             │   thread id None for General)
#    <other>  │ that specific forum topic ONLY — every other topic
#             │   (including General) is ignored
#
# Add as many entries as you need; each is filtered independently.
OTP_GROUP_IDS: list[dict] = [
    {"chat_id": -1003376156472, "topic_id": 1},
]

# Where users tap "View OTP".
OTP_VIEW_URL = "https://t.me/tempXrecever"

# ── Tunables ───────────────────────────────────────────────────────
MIN_PAYOUT           = 1.0
DEFAULT_PRICE        = 0.01
DEFAULT_NUMBER_COUNT = 2

BROADCAST_CONCURRENCY        = 100   # max in-flight sends (50–200 safe)
BROADCAST_PROGRESS_EVERY     = 1.5   # seconds between live progress edits

OTP_WORKER_COUNT = 8         # concurrent OTP matchers

# ── PostgreSQL (Supabase) ──────────────────────────────────────────
# Direct connection string.  SSL (`sslmode=require`) is auto-enabled
# inside `db.init()` when the hostname looks like a managed provider
# (Supabase / RDS / Neon / Render / Azure / Timescale Cloud /
# CockroachDB Cloud).  Pass `?sslmode=disable` in the DSN to override.
#
# Examples:
#   Supabase Session pooler (IPv4-friendly, recommended):
#     "postgresql://postgres.<PROJECT_REF>:<PASSWORD>"
#     "@aws-1-<REGION>.pooler.supabase.com:5432/postgres"
#   Direct (IPv6-only, only works on dual-stack hosts):
#     "postgresql://postgres:<PASSWORD>@db.<PROJECT_REF>.supabase.co:5432/postgres"
#   Local dev:
#     "postgresql://postgres:postgres@localhost:5432/otpbot"
DATABASE_URL = (
    "postgresql://postgres.imrifglpqbjstzxqugvu:dVqjlv7nvMbnJBks"
    "@aws-1-ap-northeast-2.pooler.supabase.com:5432/postgres"
)
DB_POOL_MIN         = 5
DB_POOL_MAX         = 30
DB_COMMAND_TIMEOUT  = 60

LOG_FILE = "logs.txt"


# ════════════════════════════════════════════════════════════════════
#                  UI PREMIUM CUSTOM-EMOJI IDS
# ────────────────────────────────────────────────────────────────────
# Every Unicode emoji used anywhere in the bot's UI maps to a
# Telegram Premium custom-emoji ID here.  Empty string = render the
# plain Unicode emoji (no premium animation).
#
# Country flag IDs live in `emojis_country.json`, and per-service
# (WhatsApp / Telegram / Facebook / …) IDs live in
# `emojis_service.json`.  Edit either JSON to rotate those.
#
# To find a custom-emoji ID:  forward any premium emoji to
# @PremiumEmojiInfo_bot or @StickerInfoBot; it replies with the ID.
#
# Bot Premium not required to display these for users — the
# `<tg-emoji>` HTML tag falls back automatically to the Unicode
# fallback when the recipient/account lacks Premium.
# ════════════════════════════════════════════════════════════════════
# Pre-populated with confident matches from three custom emoji
# packs (Vector Icons, TG iOS & macOS Icons, News Emoji).  Slots
# left empty fall back to plain Unicode — fill in any ID from
# `EMOJI_PACK_VECTOR`, `EMOJI_PACK_TG_IOS`, or `EMOJI_PACK_NEWS`
# (defined below) to enable the premium animation for that emoji.
UI_EMOJI_IDS: dict[str, str] = {
    # status / generic
    "✅": "5206607081334906820",   # News #24    big green check
    "❌": "5210952531676504517",   # News #25    big red cross
    "⚠":  "5447644880824181073",   # News #12    warning triangle
    "ℹ":  "5258423306255604960",   # TG iOS #82   info-circle
    "❓": "5436113877181941026",   # News #11    red question mark
    "💡": "5422439311196834318",   # News #89    bulb / tip
    "🆘": "5440621591387980068",   # News #64    SOS letters

    # navigation
    "⬅": "5258236805890710909",   # TG iOS #67   back / undo
    "➡": "5260450573768990626",   # TG iOS #39   forward arrow
    "🔙": "5258236805890710909",   # back  (reuses TG iOS #67)
    "⏭": "5258254475386167466",   # TG iOS #80   skip / out arrow
    "▶": "5260379144167890225",   # TG iOS #81   play arrow
    "◀": "5258236805890710909",   # back arrow (TG iOS #67)
    "⏹": "5325604415900504150",   # TG iOS #126  minus / stop
    "🔄": "5260687119092817530",   # TG iOS #69   refresh
    "♻": "5260687681733533075",   # TG iOS #66   swap arrows
    "🔘": "5316727448644103237",   # TG iOS #113  dot in circle

    # money
    "💰": "5283232570660634549",   # Vector #82   gold dollar
    "💸": "5283232570660634549",   # cash flying  (reused)
    "💎": "5359719332542718652",   # TG iOS #134  diamond
    "💲": "5283232570660634549",   # dollar sign  (reused)
    "💳": "5258096772776991776",   # TG iOS #104  wallet / card
    "💵": "5222241728659988366",   # Vector #11   "100"

    # numbers / OTP / phones
    "📞": "5258337316715373336",   # TG iOS #22  phone
    "📲": "5258337316715373336",   # phone (reused)
    "📋": "5258477770735885832",   # TG iOS #30  copy / docs
    "📑": "5258477770735885832",   # backups (reused)
    "📦": "5258389041006518073",   # TG iOS #6   box / stock
    "🔑": "",                      # key  (no good match)
    "👁": "5375338737028841420",   # News #61    eye
    "📤": "5258084656674250503",   # TG iOS #44  exit / outbox
    "📭": "5406683434124859552",   # mailbox (reuses folder)
    "📂": "5406683434124859552",   # News #97    folder
    "📥": "5406683434124859552",   # inbox (reuses folder)
    "📨": "5424818078833715060",   # incoming mail (reuses megaphone)
    "📝": "5258331647358540449",   # TG iOS #34  edit
    "📌": "5258450450448915742",   # TG iOS #20  pushpin
    "📅": "5413879192267805083",   # News #88    calendar
    "📆": "5413879192267805083",   # calendar (reused)
    "🕐": "5258215846450305872",   # TG iOS #48   clock-sync
    "⏰": "5258258882022612173",   # TG iOS #74   alarm timer
    "⏳": "5258419835922030550",   # TG iOS #73   hourglass / history

    # users / admin
    "👤": "5258011929993026890",   # TG iOS #53  person
    "👥": "5258513401784573443",   # TG iOS #32  people
    "👑": "5217822164362739968",   # News #70    crown
    "🔐": "5258476306152038031",   # TG iOS #47  lock
    "🔒": "5258476306152038031",   # lock (reused)
    "🚫": "5240241223632954241",   # News #7     prohibited (no entry)
    "📡": "5424818078833715060",   # News #47    megaphone red
    "📢": "5424818078833715060",   # broadcast   (News #47)
    "🤖": "5258093637450866522",   # TG iOS #18  robot
    "🌍": "5447410659077661506",   # News #14    globe
    "🌊": "",                      # ocean wave (no match)
    "🚀": "5391034312759980875",   # Vector #54   comet / launch
    "🎉": "5343777912883529222",   # Vector #92   party hat
    "🛠": "5341715473882955310",   # News #77    gear / tools
    "🔧": "5341715473882955310",   # wrench (reused gear icon)
    "🗑": "5258130763148172425",   # TG iOS #33  trash
    "✏": "5258215635996908355",   # TG iOS #24  pencil
    "➕": "5258108352008823107",   # TG iOS #59  plus
    "📊": "5258330865674494479",   # TG iOS #60  chart
    "🔍": "5258274739041883702",   # Vector #64   search glass
    "🔗": "5260730055880876557",   # TG iOS #28  link
    "👋": "5258077307985207053",   # TG iOS #95   hand wave
    "👇": "5258514780469075716",   # TG iOS #5    down arrow
    "🧹": "5258130763148172425",   # TG iOS #33  trash (closest match)

    # decorative / extras
    "⭐": "5258185631355378853",   # TG iOS #4   star
    "✈": "5258115571848846212",   # TG iOS #58  plane
    "🎵": "5258289810082111221",   # TG iOS #51  music
    "🌙": "5258011861273551368",   # TG iOS #50  moon
    "💗": "5337080053119336309",   # News #57    red heart
    "🏠": "5257963315258204021",   # TG iOS #43  home
    "📍": "5258509201306557640",   # TG iOS #46  location
    "🔕": "5260264520080695245",   # TG iOS #52  mute bell
    "✨": "5222108309795908493",   # Vector #3   sparkles
    "💔": "5222400230133081714",   # Vector #7   broken heart
    "🔥": "5233326571099534068",   # News #43    fire (animated)
    "❄": "5449449325434266744",   # News #85    snowflake (animated)
    "⚡": "5219943216781995020",   # Vector #6   bolt
    "💥": "5231449120635370684",   # News #44    explosion
    "🌈": "5409109841538994759",   # News #86    rainbow
    "🚨": "5395444784611480792",   # News #95    siren
    "🛍": "5395695537687123235",   # News #96    shopping bag
    "💼": "5296369303661067030",   # News #74    briefcase
    "⬇": "5406745015365943482",   # News #81    down arrow
    "🥇": "5440539497383087970",   # News #90    1st-place medal
    "🥈": "5447203607294265305",   # News #91    2nd-place medal
    "❤": "5337080053119336309",   # News #57    red heart
    "🎮": "5258508428212445001",   # TG iOS #40  gamepad
    "🎓": "5258334872878980409",   # TG iOS #41  grad cap

    # stock-state lights (no obvious match in either pack)
    "🟢": "5229064374403998351",   # News #5     green status dot
    "🟡": "",                      # yellow dot (no match)
    "🔴": "5260293700088511294",   # News #6     red status dot
}

# ────────────────────────────────────────────────────────────────────
# Reference: full ID lists for both custom-emoji packs the user
# imported.  Use these when adding/swapping IDs in UI_EMOJI_IDS
# above — `EMOJI_PACK_TG_IOS[N - 1]` gives you slot N's id, etc.
# ────────────────────────────────────────────────────────────────────
EMOJI_PACK_VECTOR: list[str] = [
    "5219899949281453881", "5222472119295684375", "5222108309795908493",
    "5219672809936006424", "5244820603663296299", "5219943216781995020",
    "5222400230133081714", "5222148368955877900", "5219901967916084166",
    "5260424249914435335", "5222241728659988366", "5219805369806629055",
    "5219866135003933502", "5220197908342648622", "5220053623211305785",
    "5246794802560774143", "5217890643321300022", "5247213725080890199",
    "5246863809800318186", "5258023599419171861", "5220070652756635426",
    "5246942081284320100", "5220046725493828505", "5303396278179210513",
    "5276489300207217985", "5294524383279198295", "5294096239464295059",
    "5278619986238122736", "5364174510708764528", "5258456562187381288",
    "5294527084813626369", "5294017134756636818", "5332423642850536254",
    "5264892613630111886", "5301096984617166561", "5301275719681190738",
    "5310224206732996002", "5377377257356537351", "5294363352070367389",
    "5314413943035278948", "5386521874089914548", "5397730656400714154",
    "5465542769755826716", "5235588635885054955", "5289862389552919154",
    "5334665104677941170", "5334811859415477124", "5292226786229236118",
    "5289940334619406906", "5335005820138564214", "5289930378885214069",
    "5391118489824015979", "5393302369024882368", "5391034312759980875",
    "5431374840332302296", "5237761614458933049", "5258391003806584549",
    "5258389638006984449", "5257961116234958730", "5258056717912000584",
    "5258024802010026053", "5258113901106580375", "5258212320282168974",
    "5258274739041883702", "5258396243666681152", "5258387666616994756",
    "5258217809250372293", "5258077595748030166", "5258281774198311547",
    "5258421738592553935", "5258296359907249075", "5258196742435787040",
    "5258466470676940666", "5258079378159453410", "5258234027046883085",
    "5258500422393415126", "5257987903945986017", "5258039825805624495",
    "5258466217273871977", "5258121851091043775", "5258450231405595367",
    "5283232570660634549", "5339135753316222622", "5339286072876614251",
    "5339233635620899144", "5341601055954194475", "5341684837881235158",
    "5341570033405412393", "5357592447557848986", "5343636681473935403",
    "5341492148468465410", "5343777912883529222", "5341357711697134290",
    "5364052602357044385", "5454371323595744068", "5452051336881271172",
    "5453900977432188793", "5453969572354878595", "5454409660473827001",
    "5453965363286925977", "5454365405130810498", "5454249887690415056",
    "5454386656628991407", "5452002073606384268", "5454079785510660283",
    "5454206993852029667", "5454360341364363439", "5454156248813432363",
    "5454245266305604993", "5454074580010295588", "5454345339043601366",
    "5454232969814238500", "5454225015534805938", "5454172148782359440",
    "5453991094435997597", "5453976908159016299", "5454419255430767770",
    "5454310635707853545",
]

EMOJI_PACK_NEWS: list[str] = [
    "5210956306952758910", "5461117441612462242", "5456140674028019486",
    "5224607267797606837", "5229064374403998351", "5260293700088511294",
    "5240241223632954241", "5274099962655816924", "5440660757194744323",
    "5314504236132747481", "5436113877181941026", "5447644880824181073",
    "5420323339723881652", "5447410659077661506", "5443038326535759644",
    "5467538555158943525", "5452069934089641166", "5231200819986047254",
    "5449683594425410231", "5447183459602669338", "5451882707875276247",
    "5244837092042750681", "5246762912428603768", "5206607081334906820",
    "5210952531676504517", "5222079954421818267", "5458603043203327669",
    "5391112412445288650", "5269531045165816230", "5395444514028529554",
    "5397782960512444700", "5409048419211682843", "5233326571099534068",
    "5231449120635370684", "5278751923338490157", "5290017777174722330",
    "5231005931550030290", "5402186569006210455", "5264919878082509254",
    "5411225014148014586", "5416081784641168838", "5416117059207572332",
    "5424972470023104089", "5276032951342088188", "5294339927318739359",
    "5224736245665511429", "5424818078833715060", "5431609822288033666",
    "5449875686837726134", "5460795800101594035", "5231012545799666522",
    "5251203410396458957", "5271604874419647061", "5282843764451195532",
    "5323442290708985472", "5334544901428229844", "5337080053119336309",
    "5348125953090403204", "5359543311897998264", "5341498088408234504",
    "5375338737028841420", "5415655814079723871", "5382357040008021292",
    "5440621591387980068", "5391032818111363540", "5397916757333654639",
    "5427168083074628963", "5438496463044752972", "5325547803936572038",
    "5217822164362739968", "5445267414562389170", "5222444124698853913",
    "5253742260054409879", "5296369303661067030", "5303479226882603449",
    "5305265301917549162", "5341715473882955310", "5361741454685256344",
    "5388632425314140043", "5386367538735104399", "5406745015365943482",
    "5402477260982731644", "5399913388845322366", "5449569374065152798",
    "5449449325434266744", "5409109841538994759", "5393512611968995988",
    "5413879192267805083", "5422439311196834318", "5440539497383087970",
    "5447203607294265305", "5453902265922376865", "5463107823946717464",
    "5406756500108501710", "5395444784611480792", "5395695537687123235",
    "5406683434124859552", "5416041192905265756", "5460755126761312667",
    "5461151367559141950",
]

EMOJI_PACK_TG_IOS: list[str] = [
    "5226513232549664618", "5258050709252743821", "5258362837411045098",
    "5258185631355378853", "5258514780469075716", "5258389041006518073",
    "5258226313285607065", "5260280853841321805", "5258071638628377037",
    "5258123337149717894", "5258318620722733379", "5258169263235013408",
    "5258145898612924124", "5257965174979042426", "5258368777350816286",
    "5258152182150077732", "5258328383183396223", "5258093637450866522",
    "5258260149037965799", "5258450450448915742", "5258105663359294787",
    "5258337316715373336", "5258205968025525531", "5258215635996908355",
    "5260268501515377807", "5260726538302660868", "5260342697075416641",
    "5260730055880876557", "5257974976094412956", "5258477770735885832",
    "5258507474729704350", "5258513401784573443", "5258130763148172425",
    "5258331647358540449", "5260233433107407649", "5258430848218176413",
    "5257965810634202885", "5257969839313526622", "5260450573768990626",
    "5258508428212445001", "5258334872878980409", "5258179403652801593",
    "5257963315258204021", "5258084656674250503", "5258216851472654189",
    "5258509201306557640", "5258476306152038031", "5258215846450305872",
    "5260535596941582167", "5258011861273551368", "5258289810082111221",
    "5260264520080695245", "5258011929993026890", "5258334469152054985",
    "5257991477358763590", "5260399854500191689", "5258461531464539536",
    "5258115571848846212", "5258108352008823107", "5258330865674494479",
    "5260221883940347555", "5258501105293205250", "5258420634785947640",
    "5260412365739925015", "5258212268742549391", "5260687681733533075",
    "5258236805890710909", "5258474669769497337", "5260687119092817530",
    "5260249440450520061", "5258200019495821936", "5258336354642697821",
    "5258419835922030550", "5258258882022612173", "5260341314095947411",
    "5260416304224936047", "5258057130228849960", "5260652420052032852",
    "5258043150110301407", "5258254475386167466", "5260379144167890225",
    "5258423306255604960", "5258503720928288433", "5258215850745275216",
    "5258262708838472996", "5258267368877989660", "5258391025281408576",
    "5258453452631056344", "5258089153505009279", "5258073068852485953",
    "5260512129240276089", "5258486128742244085", "5258134813302332906",
    "5258362429389152256", "5258077307985207053", "5258020476977946656",
    "5258391252914676042", "5258132936401624790", "5258318251355545562",
    "5258278668936945760", "5199457120428249992", "5260652149469094137",
    "5258204546391351475", "5258096772776991776", "5258165702707125574",
    "5260348422266822411", "5274008024585871702", "5271934788037517525",
    "5429411030960711866", "5427181942934088912", "5204189706237004154",
    "5260325873688518261", "5316727448644103237", "5256143829672672750",
    "5258012149036365477", "5255813559572508065", "5249231689695115145",
    "5296348778012361146", "5296385246579670377", "5296678515536581003",
    "5323761960829862762", "5323404142809467476", "5429571366384842791",
    "5253959125838090076", "5275969776668134187", "5325604415900504150",
    "5323585953070074710", "5357069174512303778", "5267123797600783095",
    "5452165780579843515", "5296727963495079440", "5359629206948976159",
    "5359529383319084413", "5359719332542718652",
]

# Register the table immediately so every later HTML message body —
# whether sent via aiogram, broadcast, or callback edit — gets the
# emojis auto-wrapped before going on the wire.
emojis.set_ui_ids(UI_EMOJI_IDS)


# ════════════════════════════════════════════════════════════════════
#                            Logging
# ════════════════════════════════════════════════════════════════════
log = logging.getLogger("bot")
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
for noisy in ("httpx", "aiogram", "aiogram.event", "aiogram.dispatcher",
              "pyrogram", "pyrogram.session", "pyrogram.connection"):
    logging.getLogger(noisy).setLevel(logging.WARNING)


def log_message(msg: str) -> None:
    core.append_log_line(LOG_FILE, msg)


# ════════════════════════════════════════════════════════════════════
#                       In-memory session state
# ════════════════════════════════════════════════════════════════════
# Replaces PTB's `context.user_data`.  Per-user dict, lives only in
# memory — the original bot didn't persist these either.
USER_STATE: dict[int, dict[str, Any]] = {}
_background_tasks: set[asyncio.Task] = set()


def state(user_id: int) -> dict[str, Any]:
    return USER_STATE.setdefault(int(user_id), {})


def clear_state(user_id: int) -> None:
    USER_STATE.pop(int(user_id), None)


def is_owner(user_id: int) -> bool:
    return int(user_id) == OWNER_ID


def is_admin(user_id: int) -> bool:
    uid = int(user_id)
    return uid == OWNER_ID or uid in db.ADMIN_IDS


def admin_kb(user_id: int) -> ReplyKeyboardMarkup:
    return core.admin_keyboard(user_id, OWNER_ID)


def safe_task(coro, *, name: str | None = None) -> asyncio.Task:
    return core.safe_create_task(coro, name=name, pool=_background_tasks)


# ════════════════════════════════════════════════════════════════════
#                           Force-join
# ════════════════════════════════════════════════════════════════════
async def check_force_join(user_id: int, bot: Bot) -> tuple[bool, list[int]]:
    fj = db.FORCE_JOIN
    if not fj.get("enabled") or not fj.get("chats"):
        return True, []
    not_joined: list[int] = []
    for i, entry in enumerate(fj["chats"]):
        chat_id = entry.get("chat_id")
        if not chat_id:
            continue
        try:
            member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
            if member.status in (ChatMemberStatus.LEFT,
                                 ChatMemberStatus.KICKED,
                                 ChatMemberStatus.RESTRICTED):
                # `RESTRICTED` is treated as "not joined" only when
                # the restriction excludes membership; aiogram never
                # raises here, so fall back to the original behaviour.
                if member.status != ChatMemberStatus.RESTRICTED:
                    not_joined.append(i)
        except Exception:                       # noqa: BLE001
            not_joined.append(i)
    return len(not_joined) == 0, not_joined


def _missing_chat_entries(not_joined: list[int]) -> list[dict]:
    chats = db.FORCE_JOIN.get("chats", [])
    return [chats[i] for i in not_joined if 0 <= i < len(chats)]


def _build_fj_buttons(not_joined: list[int]) -> InlineKeyboardMarkup:
    _, kb = core.force_join_user_text(_missing_chat_entries(not_joined))
    return kb


async def send_force_join_prompt(message: Message,
                                 not_joined: list[int] | None = None
                                 ) -> None:
    chats = db.FORCE_JOIN.get("chats", [])
    if not_joined is None:
        not_joined = list(range(len(chats)))
    text, kb = core.force_join_user_text(_missing_chat_entries(not_joined))
    await message.answer(text, reply_markup=kb)


# ════════════════════════════════════════════════════════════════════
#                        OTP pipeline
# ════════════════════════════════════════════════════════════════════
# Queue payload: (chat_id, message_id, text).  message_id is used
# ONLY to suppress true Pyrogram redelivery (rare, happens during
# reconnect / catch-up).  We deliberately do NOT dedupe on content,
# so if the same OTP arrives twice as two distinct group messages
# the user receives both — which is what users expect.
#
# IMPORTANT: created lazily inside main() so it binds to the running
# event loop.  Python 3.13+ refuses to share asyncio.Queue / Event
# instances across event loops.  See _ensure_otp_queue() below.
OTP_QUEUE: asyncio.Queue[tuple[int, int, str]] | None = None
_seen_message_ids: dict[tuple[int, int], float] = {}


def _ensure_otp_queue() -> asyncio.Queue:
    global OTP_QUEUE
    if OTP_QUEUE is None:
        OTP_QUEUE = asyncio.Queue(maxsize=10000)
    return OTP_QUEUE


async def enqueue_otp(chat_id: int, message_id: int, text: str) -> None:
    """Called by the Pyrogram listener — adds work to the queue."""
    q = _ensure_otp_queue()
    try:
        q.put_nowait((chat_id, int(message_id or 0), text))
    except asyncio.QueueFull:
        log.warning("OTP_QUEUE full — message dropped (chat=%s)", chat_id)


def _is_redelivery(chat_id: int, message_id: int) -> bool:
    """True only when we've already seen this exact chat/message pair
    within the last 5 minutes.  Same OTP digits in a *different* group
    message → False (forwarded normally).

    Dedupe is RAM-first for hot-path latency; the PG `processed_messages`
    table is updated fire-and-forget so the dedupe survives restarts
    (the bootstrap loop in main() warms RAM from the last hour of rows).
    """
    if not message_id:           # service msgs / nameless — never dedupe
        return False
    key = (int(chat_id), int(message_id))
    now = time.time()
    if key in _seen_message_ids:
        return True
    _seen_message_ids[key] = now
    # Mirror to PG (fire-and-forget; never blocks).
    db._enqueue(
        """INSERT INTO processed_messages (chat_id, message_id)
           VALUES ($1, $2)
           ON CONFLICT (chat_id, message_id) DO NOTHING""",
        (int(chat_id), int(message_id)),
    )
    if len(_seen_message_ids) > 5000:
        cutoff = now - 300
        for k, ts in list(_seen_message_ids.items()):
            if ts < cutoff:
                _seen_message_ids.pop(k, None)
    return False


async def _warm_dedupe_from_pg() -> None:
    """Pull the last hour of (chat_id, message_id) into RAM at startup so
    the dedupe survives restarts within the cooldown window.
    """
    try:
        async with db.pool().acquire() as conn:
            rows = await conn.fetch(
                """SELECT chat_id, message_id, EXTRACT(EPOCH FROM seen_at)::float AS ts
                   FROM processed_messages
                   WHERE seen_at > NOW() - INTERVAL '1 hour'
                   ORDER BY seen_at DESC
                   LIMIT 5000""",
            )
        for r in rows:
            _seen_message_ids[(int(r["chat_id"]), int(r["message_id"]))] = (
                float(r["ts"])
            )
        log.info("Warmed dedupe with %d entries from PG", len(rows))
    except Exception as e:                            # noqa: BLE001
        log.warning("Could not warm dedupe from PG: %s", e)


async def _processed_messages_janitor() -> None:
    """Background task: prune old rows from `processed_messages` daily."""
    while True:
        try:
            await asyncio.sleep(3600)
            removed = await db.prune_processed_messages(86400)
            if removed:
                log.info("Pruned %d old processed_messages rows", removed)
        except asyncio.CancelledError:
            break
        except Exception as e:                        # noqa: BLE001
            log.warning("processed_messages janitor error: %s", e)


async def _process_one_otp(bot: Bot, chat_id: int, message_id: int,
                           text: str) -> None:
    """Translate raw group message → match → forward → persist.

    Mirrors the original `otp_listener()` logic but with no blocking
    I/O: matching is a fast in-memory scan, the user is notified
    BEFORE state mutations, and persistence is fire-and-forget via
    the aiosqlite writer queue.

    The only message we drop is one that Pyrogram has already
    delivered to us a few seconds ago (redelivery on reconnect).
    Two *separate* group messages with identical content are both
    forwarded.
    """
    if _is_redelivery(chat_id, message_id):
        return

    number, otp_digits, otp_pretty = core.parse_otp(text)
    if not otp_digits:
        log_message("No valid OTP found")
        return

    if not number:
        log_message("OTP found but no phone number — dropped")
        return

    norm_target = core.normalize_phone(number)

    matched_uid: str | None = None
    matched_user: dict | None = None
    # Iterate over a snapshot — concurrent aiogram handlers can mutate
    # db.USERS at any time and we must not raise "dictionary changed
    # size during iteration".
    for uid, udata in list(db.USERS.items()):
        if not udata.get("awaiting_otp"):
            continue
        user_numbers = list(udata.get("current_numbers") or [])
        primary = udata.get("current_number")
        if primary and primary not in user_numbers:
            user_numbers.insert(0, primary)
        if any(core.normalize_phone(n) == norm_target for n in user_numbers):
            matched_uid = uid
            matched_user = udata
            break

    if matched_uid is None or matched_user is None:
        db.append_otp_log(None, number, otp_digits)
        log_message(f"OTP {otp_digits} for {number} - no matching user")
        return

    user_country = matched_user.get("current_country")
    c_info = db.COUNTRIES["countries"].get(user_country, {}) if user_country else {}
    price = float(c_info.get("price", DEFAULT_PRICE))
    payout_on = bool(db.CONFIG.get("payout_enabled", True))

    c_display = c_info.get("display_name", user_country or "Unknown")
    c_dial = c_info.get("dial_code", "")
    c_iso = c_info.get("iso", "")
    c_service = (c_info.get("service") or "").strip().upper() or None
    country_label = f"{c_display} ({c_dial})" if c_dial else c_display

    new_balance = float(matched_user.get("balance", 0)) + (price if payout_on else 0)
    new_balance = round(new_balance, 4)

    msg_text = core.build_otp_user_message(
        country_label=country_label,
        number=number,
        otp_pretty=otp_pretty or otp_digits,
        payout_on=payout_on,
        price=price,
        new_balance=new_balance,
        iso=c_iso,
        service=c_service,
        country_display=c_display,
    )
    msg_kb = core.otp_received_buttons(otp_digits,
                                       view_url=OTP_VIEW_URL,
                                       service=c_service)

    # ── 1) Notify user FIRST — no disk I/O on the critical path ──
    # Flood-wait aware: if Telegram tells us to back off, sleep the
    # exact duration it asks for and retry.  This guarantees that
    # under burst traffic the user still receives every OTP.
    sent = False
    for attempt in range(3):
        try:
            await bot.send_message(chat_id=int(matched_uid),
                                   text=msg_text,
                                   reply_markup=msg_kb)
            sent = True
            break
        except Exception as e:                  # noqa: BLE001
            wait_for = getattr(e, "retry_after", None)
            if wait_for is None and "FLOOD_WAIT" in str(e).upper():
                m = re.search(r"FLOOD_WAIT_(\d+)", str(e))
                if m:
                    wait_for = int(m.group(1))
            if wait_for and attempt < 2:
                log_message(f"OTP send flood-wait {wait_for}s "
                            f"(uid={matched_uid}, attempt={attempt+1})")
                await asyncio.sleep(min(int(wait_for) + 1, 60))
                continue
            log_message(f"Failed to notify {matched_uid}: {e}")
            break
    if not sent:
        # Couldn't deliver — DO NOT credit balance / increment counters
        # so the user can be retried later.  Still log so we know.
        db.append_otp_log(matched_uid, number, otp_digits)
        return

    # ── 2) Update in-memory state & enqueue persistence ──
    matched_user["otps"] = int(matched_user.get("otps", 0)) + 1
    if payout_on:
        matched_user["balance"] = new_balance
    if user_country and user_country in db.COUNTRIES["countries"]:
        c = db.COUNTRIES["countries"][user_country]
        c["total_otps"] = int(c.get("total_otps", 0)) + 1
        if payout_on:
            c["total_earnings"] = round(
                float(c.get("total_earnings", 0.0)) + price, 4)
        db.save_country(user_country)

    db.save_user(matched_uid)
    db.append_otp_log(matched_uid, number, otp_digits)
    core.track_daily_otp(user_country, price if payout_on else 0)

    log_message(
        f"OTP {otp_digits} for {number} -> user {matched_uid} "
        f"(payout={'ON' if payout_on else 'OFF'})"
    )

    # Premium 'Incoming OTP' log forward (admin-side log channel).
    try:
        fwd_text = core.build_forwarded_otp_text(
            iso=c_iso,
            country_display=c_display,
            service=c_service,
            number=number,
            otp_digits=otp_digits,
            otp_pretty=otp_pretty or otp_digits,
        )
        await _maybe_log_forward(bot, fwd_text)
    except Exception as e:                       # noqa: BLE001
        log.warning("Forward log failed: %s", e)


async def otp_worker(bot: Bot) -> None:
    """Concurrent worker: drains OTP_QUEUE forever."""
    q = _ensure_otp_queue()
    while True:
        chat_id, message_id, text = await q.get()
        try:
            await _process_one_otp(bot, chat_id, message_id, text)
        except Exception as e:                  # noqa: BLE001
            log.error("otp_worker error: %s", e, exc_info=True)
        finally:
            q.task_done()


# ════════════════════════════════════════════════════════════════════
#                  Pyrogram MTProto group reader
# ════════════════════════════════════════════════════════════════════
def _build_pyrogram_client():
    """Create a Pyrogram client.  Imports are lazy so the bot still
    starts when Pyrogram is missing, surfacing a clear error log
    instead of a silent crash at import time.
    """
    try:
        from pyrogram import Client                     # noqa: WPS433
    except ImportError:
        log.error("pyrogram not installed — MTProto reading disabled. "
                  "pip install pyrogram tgcrypto")
        return None

    kwargs: dict[str, Any] = {
        "name":     "user_session" if not PYRO_SESSION else "user_session_str",
        "api_id":   API_ID,
        "api_hash": API_HASH,
        "workers":  4,
        "in_memory": bool(PYRO_SESSION),
    }
    if PYRO_SESSION:
        kwargs["session_string"] = PYRO_SESSION
    else:
        kwargs["phone_number"] = USER_PHONE
        kwargs["password"] = USER_2FA
    return Client(**kwargs)


def _normalise_topic_id(raw: Any) -> int | None:
    """`null` / missing / 0 / "" / "0" → read the whole group.
    Anything else is the explicit topic id we will match against.
    """
    if raw is None or raw == "":
        return None
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


# chat_id → topic_id (None means "read the whole chat — no topic filter")
_CHANNEL_TOPIC_MAP: dict[int, int | None] = {
    int(ch["chat_id"]): _normalise_topic_id(ch.get("topic_id"))
    for ch in OTP_GROUP_IDS
}
_OTP_CHAT_IDS: list[int] = list(_CHANNEL_TOPIC_MAP)

# Log the resolved filter at import time so it's obvious in the
# console which mode each watched chat is in.
for _cid, _tid in _CHANNEL_TOPIC_MAP.items():
    if _tid is None:
        log.warning("OTP filter: chat=%s — reading WHOLE group (no topic filter)", _cid)
    elif _tid == 1:
        log.warning("OTP filter: chat=%s — General topic only", _cid)
    else:
        log.warning("OTP filter: chat=%s — topic_id=%s only", _cid, _tid)

# Per-chat watermark for catch-up on reconnect (mirrors original
# Telethon `_last_seen_msg_id` but per-chat, which is more correct).
_LAST_SEEN_PER_CHAT: dict[int, int] = {cid: 0 for cid in _OTP_CHAT_IDS}


def _topic_id_for(message) -> int | None:
    """Pyrogram's forum-topic identifier for the message.

    Order of preference:
      1. `message.message_thread_id` — set by Pyrogram on every
         message that lives inside a forum topic (top-level posts
         AND replies under a topic).
      2. `message.reply_to_top_message_id` — fallback for older
         Pyrogram builds where (1) is None on plain replies.
      3. nested `message.reply_to_message.reply_to_top_message_id`
         — extra fallback for very old releases that exposed it
         only via the reply header.

    We deliberately do NOT fall back to `reply_to_message_id` —
    that's the *parent of a regular reply*, not a topic id.
    """
    tid = getattr(message, "message_thread_id", None)
    if tid:
        return int(tid)
    tid = getattr(message, "reply_to_top_message_id", None)
    if tid:
        return int(tid)
    rep = getattr(message, "reply_to_message", None)
    if rep is not None:
        tid = getattr(rep, "reply_to_top_message_id", None)
        if tid:
            return int(tid)
    return None


def _topic_matches(message, expected_topic_id: int | None) -> bool:
    """Filtering rules:

      * `expected_topic_id is None`  → accept every message in the chat.
      * `expected_topic_id == 1`     → General topic only (Pyrogram
                                       leaves the topic id `None` there
                                       — same for non-forum chats).
      * otherwise (specific topic)   → message's topic id must match
                                       exactly.  Messages in any other
                                       topic (including General) are
                                       rejected.
    """
    if expected_topic_id is None:
        return True
    actual = _topic_id_for(message)
    if expected_topic_id == 1:
        return actual is None
    return actual == expected_topic_id


async def _handle_pyrogram_message(message) -> None:
    """Filter + enqueue.  Used by both live handler and catch-up."""
    try:
        chat_id = int(message.chat.id)
        if chat_id not in _CHANNEL_TOPIC_MAP:
            return
        text = getattr(message, "text", None) or getattr(message, "caption", None)
        if not text:
            return
        if not _topic_matches(message, _CHANNEL_TOPIC_MAP[chat_id]):
            return

        msg_id = int(getattr(message, "id", 0) or 0)
        # Update high-water mark for next catch-up window.
        if msg_id > _LAST_SEEN_PER_CHAT.get(chat_id, 0):
            _LAST_SEEN_PER_CHAT[chat_id] = msg_id

        await enqueue_otp(chat_id, msg_id, text)
    except Exception as e:                              # noqa: BLE001
        log.error("Pyrogram handler error: %s", e)


async def _pyrogram_catch_up(client) -> None:
    """After a reconnect, fetch any messages we missed while offline.

    Iterates each watched chat from the last seen msg id forward,
    applying the same topic filter as the live handler.  Mirrors
    the original `_catch_up_missed()`.
    """
    for chat_id, last_seen in list(_LAST_SEEN_PER_CHAT.items()):
        if last_seen <= 0:
            continue
        try:
            missed = []
            async for msg in client.get_chat_history(chat_id, limit=200):
                m_id = int(getattr(msg, "id", 0) or 0)
                if m_id <= last_seen:
                    break
                missed.append(msg)
            if missed:
                log.warning("Pyrogram catch-up: %d missed (chat=%s)",
                            len(missed), chat_id)
                log_message(
                    f"Pyrogram catch-up: {len(missed)} missed message(s) "
                    f"(chat={chat_id})"
                )
                # Process oldest → newest so timestamps stay monotonic.
                for msg in reversed(missed):
                    await _handle_pyrogram_message(msg)
        except Exception as e:                          # noqa: BLE001
            log.error("Pyrogram catch-up error (chat=%s): %s", chat_id, e)


async def _pyrogram_seed_watermarks(client) -> None:
    """On first connect, record the latest message id per chat so that
    a future reconnect's catch-up only fetches messages newer than this.
    """
    for chat_id in _OTP_CHAT_IDS:
        try:
            async for msg in client.get_chat_history(chat_id, limit=1):
                m_id = int(getattr(msg, "id", 0) or 0)
                if m_id > _LAST_SEEN_PER_CHAT.get(chat_id, 0):
                    _LAST_SEEN_PER_CHAT[chat_id] = m_id
                break
        except Exception:                               # noqa: BLE001
            pass


async def _pyrogram_keepalive(client, stop_event: asyncio.Event) -> None:
    """Ping every 45 s — guards against silent dead TCP connections.
    Pyrogram has its own pings, but an explicit `get_me()` round-trip
    surfaces a half-open socket faster.  After 3 consecutive failures
    we set the stop event so the outer loop forces a reconnect; the
    auto-reconnect inside Pyrogram cannot recover a half-open socket.
    """
    failures = 0
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=45)
            return
        except asyncio.TimeoutError:
            pass
        try:
            if client.is_connected:
                await client.get_me()
            failures = 0
        except Exception as e:                          # noqa: BLE001
            failures += 1
            log.warning("Pyrogram keepalive failure #%d: %s", failures, e)
            if failures >= 3:
                log.warning(
                    "Pyrogram keepalive: 3 failures in a row — "
                    "forcing reconnect"
                )
                stop_event.set()
                return


async def _pyrogram_login():
    """One-time Pyrogram start.  Prompts the user interactively for
    the SMS code on first run; subsequent runs reuse the saved
    `user_session.session` file silently.

    Returns the started Pyrogram client, or None if Pyrogram isn't
    installed / configured.
    """
    pyro_client = _build_pyrogram_client()
    if pyro_client is None:
        return None

    try:
        from pyrogram import filters                     # noqa: WPS433
        from pyrogram.handlers import MessageHandler     # noqa: WPS433
    except ImportError:
        log.error("pyrogram missing — listener disabled")
        return None

    # Register the live message handler once on the persistent client.
    async def _live_handler(_client, message):           # noqa: ANN001
        await _handle_pyrogram_message(message)

    pyro_client.add_handler(
        MessageHandler(_live_handler, filters.chat(_OTP_CHAT_IDS))
    )

    try:
        await pyro_client.start()
    except Exception as e:                              # noqa: BLE001
        log.error("Pyrogram login failed: %s", e, exc_info=True)
        log_message(f"Pyrogram login failed: {e}")
        return None

    log.warning("Pyrogram connected")
    log_message("Pyrogram connected")
    await _pyrogram_seed_watermarks(pyro_client)
    return pyro_client


async def _pyrogram_keepalive_loop(pyro_client) -> None:
    """Long-lived background loop: keeps the Pyrogram session alive,
    reconnects with exponential backoff, and replays any messages
    we missed while disconnected.
    """
    backoff = 1
    while True:
        stop_event = asyncio.Event()
        keepalive_task: asyncio.Task | None = None
        try:
            if not pyro_client.is_connected:
                await pyro_client.start()
                log.warning("Pyrogram reconnected")
                log_message("Pyrogram reconnected")
                await _pyrogram_catch_up(pyro_client)
                backoff = 1

            keepalive_task = asyncio.create_task(
                _pyrogram_keepalive(pyro_client, stop_event),
                name="pyrogram-keepalive",
            )
            _background_tasks.add(keepalive_task)
            keepalive_task.add_done_callback(_background_tasks.discard)

            await stop_event.wait()
            log.warning("Pyrogram: keepalive forced reconnect")
            log_message("Pyrogram: keepalive forced reconnect")
        except Exception as e:                          # noqa: BLE001
            log.error("Pyrogram disconnect: %s — backoff %ds", e, backoff)
            log_message(f"Pyrogram disconnect: {e}")
        finally:
            if keepalive_task and not keepalive_task.done():
                keepalive_task.cancel()
            try:
                if pyro_client.is_connected:
                    await pyro_client.stop()
            except Exception:                           # noqa: BLE001
                pass

        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 30)


# ════════════════════════════════════════════════════════════════════
#                      aiogram bot — handlers
# ════════════════════════════════════════════════════════════════════
dp = Dispatcher()


# ────────────────────────────────────────────────────────────────────
# Premium-emoji auto-wrapping for ALL outgoing HTML text.
# Patches the three aiogram entry points we use (Message.answer,
# Bot.send_message, Bot.edit_message_text) so every string passes
# through `emojis.premium_html()` exactly once before going on the
# wire.  No-op when `UI_EMOJI_IDS` is empty (everyone sees plain
# Unicode) — flips on the moment any IDs are filled in at the top
# of this file.
# ────────────────────────────────────────────────────────────────────
def _premium(text):                                  # noqa: ANN001
    if isinstance(text, str):
        return emojis.premium_html(text)
    return text

_orig_msg_answer    = Message.answer
_orig_msg_reply     = Message.reply
_orig_msg_edit_text = Message.edit_text
_orig_bot_send      = Bot.send_message
_orig_bot_edit      = Bot.edit_message_text

async def _patched_msg_answer(self: Message, text: str = "", **kw):
    return await _orig_msg_answer(self, _premium(text), **kw)

async def _patched_msg_reply(self: Message, text: str = "", **kw):
    return await _orig_msg_reply(self, _premium(text), **kw)

async def _patched_msg_edit_text(self: Message, text: str = "", **kw):
    return await _orig_msg_edit_text(self, _premium(text), **kw)

async def _patched_bot_send(self: Bot, chat_id, text: str = "", **kw):
    return await _orig_bot_send(self, chat_id, _premium(text), **kw)

async def _patched_bot_edit(self: Bot, text: str = "", **kw):
    return await _orig_bot_edit(self, _premium(text), **kw)

Message.answer        = _patched_msg_answer        # type: ignore[assignment]
Message.reply         = _patched_msg_reply         # type: ignore[assignment]
Message.edit_text     = _patched_msg_edit_text     # type: ignore[assignment]
Bot.send_message      = _patched_bot_send          # type: ignore[assignment]
Bot.edit_message_text = _patched_bot_edit          # type: ignore[assignment]

# All menu button labels (both legacy "📞Get Number" and the new
# spaced "📞 Get Number" variants).  We match on the leading emoji-
# and-text combo plus a stripped-emoji form, so existing chat states
# don't break for users running an older keyboard.
_MENU_LABELS = (
    "Get Number", "Clear Prefix", "My Balance", "Withdraw", "Help",
    "Stock Check",
    "User Panel", "User Mode", "Admin Panel",
    "Add Country", "Remove Country", "Manage Numbers", "Country Stats",
    "Bot Stats", "Toggle Payout", "Payouts", "Broadcast",
    "Log Forwarding", "Admin Management", "Force Join",
    "Import Users", "Export Users",
    "Owner", "Back to Admin",
)


def _menu_action(text: str) -> str | None:
    """Normalise a button-press → canonical action name (or None).
    Tolerant of leading emoji, optional spaces, capitalisation.
    """
    if not text:
        return None
    # Strip emoji prefix(es) up to first ASCII letter.
    t = text
    while t and not (t[0].isalnum()):
        t = t[1:]
    t = t.strip()
    for label in _MENU_LABELS:
        if t.lower() == label.lower():
            return label
    return None


# Used in the catch-all "is this a menu press?" check below.
MENU_BUTTONS = {
    "📞Get Number", "🧹Clear Prefix", "💰My Balance", "💸Withdraw", "❓Help",
    "📦Stock Check", "📦 Stock Check",
    "📞 Get Number", "🧹 Clear Prefix", "💰 My Balance", "💸 Withdraw",
    "❓ Help",
    "👤User Panel", "👤User Mode", "🔐Admin Panel",
    "👤 User Panel", "👤 User Mode", "🔐 Admin Panel",
    "🌍Add Country", "❌Remove Country", "📋Manage Numbers", "📊Country Stats",
    "🤖Bot Stats", "🔄Toggle Payout", "💳Payouts", "📢Broadcast",
    "📡Log Forwarding", "👥Admin Management", "🚫Force Join",
    "🌍 Add Country", "❌ Remove Country", "📋 Manage Numbers",
    "📊 Country Stats", "🤖 Bot Stats", "🔄 Toggle Payout", "💳 Payouts",
    "📢 Broadcast", "📡 Log Forwarding", "👥 Admin Management",
    "🚫 Force Join",
    "📥 Import Users", "📤 Export Users",
    "👑Owner", "👑 Owner",
    "⬅️Back to Admin", "⬅️ Back to Admin",
}


# ────────────────────────────────────────────────────────────────────
# /start
# ────────────────────────────────────────────────────────────────────
@dp.message(Command("start"))
async def cmd_start(message: Message, bot: Bot) -> None:
    user = message.from_user
    uid = str(user.id)
    core.ensure_user(uid, user.username)
    clear_state(user.id)

    if not is_admin(user.id):
        all_joined, not_joined = await check_force_join(user.id, bot)
        if not all_joined:
            await send_force_join_prompt(message, not_joined)
            return

    if is_admin(user.id):
        await message.answer(
            "👋<b>Welcome Admin!</b>\nChoose your panel:",
            reply_markup=core.login_keyboard(),
        )
    else:
        await message.answer(
            "👋<b>Welcome!</b>\nUse the buttons below to get started.",
            reply_markup=core.user_keyboard(),
        )


# ────────────────────────────────────────────────────────────────────
# Bot chat-member tracking — populates BOT_KNOWN_CHATS for "Scan Bot's
# Groups".
# ────────────────────────────────────────────────────────────────────
@dp.my_chat_member()
async def on_my_chat_member(update: ChatMemberUpdated) -> None:
    chat = update.chat
    new_status = update.new_chat_member.status
    cid_str = str(chat.id)

    if new_status in (ChatMemberStatus.MEMBER,
                      ChatMemberStatus.ADMINISTRATOR,
                      ChatMemberStatus.CREATOR):
        db.BOT_KNOWN_CHATS[cid_str] = {
            "title":   chat.title or chat.full_name or cid_str,
            "type":    chat.type,
            "chat_id": chat.id,
        }
        db.save_bot_known_chat(chat.id)
        for entry in db.FORCE_JOIN.get("chats", []):
            if entry.get("chat_id") == chat.id:
                entry["title"] = chat.title or cid_str
                entry.pop("invite_only", None)
        db.save_force_join()
        log_message(f"Bot joined/updated in chat: {chat.title} ({chat.id})")
    elif new_status in (ChatMemberStatus.LEFT, ChatMemberStatus.KICKED):
        db.delete_bot_known_chat(chat.id)
        log_message(f"Bot left/kicked from chat: {chat.id}")


# ────────────────────────────────────────────────────────────────────
# Document handler — number uploads
# ────────────────────────────────────────────────────────────────────
@dp.message(F.document)
async def on_document(message: Message, bot: Bot) -> None:
    if not is_admin(message.from_user.id):
        return
    s = state(message.from_user.id)

    # Owner: Import Users — accepts .txt / .csv with user IDs.
    if s.get("awaiting_import_users") and is_owner(message.from_user.id):
        await _handle_import_users_file(message, s, bot)
        return

    if not s.get("awaiting_file"):
        return
    if not message.document:
        await message.answer("Send a document file.")
        return

    path = f"numbers_upload_{int(time.time())}.txt"
    await bot.download(message.document, destination=path)
    try:
        with open(path, "r", encoding="utf-8") as f:
            nums = [line.strip() for line in f if line.strip()]
    finally:
        try:
            os.remove(path)
        except Exception:                       # noqa: BLE001
            pass

    buf = s.setdefault("upload_buffer", [])
    buf.extend(nums)
    s["upload_file_count"] = s.get("upload_file_count", 0) + 1
    fc = s["upload_file_count"]
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅DONE UPLOAD",
                              callback_data="upload_done")],
        [InlineKeyboardButton(text="❌Cancel",
                              callback_data="upload_cancel")],
    ])
    await message.answer(
        f"✅File {fc} received: <b>{len(nums)}</b> lines\n"
        f"📦Buffer total: <b>{len(buf)}</b> numbers\n\n"
        f"Send more files or press <b>✅DONE UPLOAD</b>.",
        reply_markup=keyboard,
    )


# ════════════════════════════════════════════════════════════════════
#                           Text handler
# (Big router — preserves every awaiting-state branch from main122.)
# ════════════════════════════════════════════════════════════════════
@dp.message(F.text)
async def on_text(message: Message, bot: Bot) -> None:
    user = message.from_user
    user_id = str(user.id)
    u = core.ensure_user(user_id, user.username)
    s = state(user.id)
    text = (message.text or "").strip()
    db.COUNTRIES.setdefault("countries", {})

    # Reset awaiting state when a menu button is pressed.
    if text in MENU_BUTTONS:
        clear_state(user.id)
        s = state(user.id)

    # ── Admin awaiting states ────────────────────────────────────
    if is_admin(user.id):
        if s.get("awaiting_country"):
            await _handle_awaiting_country(message, s, text)
            return
        if s.get("awaiting_price"):
            await _handle_awaiting_price(message, s, text)
            return
        if s.get("awaiting_user_limit"):
            await _handle_awaiting_user_limit(message, s, text)
            return
        if s.get("awaiting_user_limit_all"):
            await _handle_awaiting_user_limit_all(message, s, text)
            return
        if s.get("awaiting_log_group_id"):
            await _handle_awaiting_log_group_id(message, s, text)
            return
        if s.get("awaiting_admin_id"):
            await _handle_awaiting_admin_id(message, s, text)
            return
        if s.get("awaiting_fj_links"):
            await _handle_awaiting_fj_links(message, s, text, bot)
            return
        if s.get("awaiting_fj_private_id"):
            await _handle_awaiting_fj_private_id(message, s, text)
            return
        if s.get("awaiting_fj_names"):
            await _handle_awaiting_fj_names(message, s, text)
            return
        if s.get("awaiting_file"):
            await _handle_awaiting_text_numbers(message, s, text)
            return
        if s.get("awaiting_broadcast"):
            await _handle_awaiting_broadcast(message, s, text)
            return
        if s.get("awaiting_daily_date"):
            await _handle_awaiting_daily_date(message, s, text)
            return
        if s.get("awaiting_daily_range"):
            await _handle_awaiting_daily_range(message, s, text)
            return

    # ── Payout flow (user side) ──────────────────────────────────
    step = s.get("awaiting_payout_step")
    if step:
        await _handle_payout_step(message, s, text, u, step)
        return

    # ── Login / mode switch ──────────────────────────────────────
    action = _menu_action(text)
    if action in ("User Panel", "User Mode"):
        clear_state(user.id)
        await message.answer("👤 <b>User Mode Activated</b>",
                             reply_markup=core.user_keyboard())
        return
    if action == "Admin Panel":
        if is_admin(user.id):
            clear_state(user.id)
            await message.answer("🔐 <b>Admin Panel Activated</b>",
                                 reply_markup=admin_kb(user.id))
        else:
            clear_state(user.id)
            await message.answer("❌ <b>Unauthorized.</b>",
                                 reply_markup=core.user_keyboard())
        return

    # ── Force-join gate (non-admin) ──────────────────────────────
    if not is_admin(user.id):
        all_joined, not_joined = await check_force_join(user.id, bot)
        if not all_joined:
            await send_force_join_prompt(message, not_joined)
            return

    # ── User-side menu buttons ───────────────────────────────────
    if action == "Get Number":
        await _user_get_number(message, u)
        return

    if action == "Clear Prefix":
        await _user_clear_prefix(message, u)
        return

    if action == "My Balance":
        await _user_balance(message, u)
        return

    if action == "Stock Check":
        sc_text, sc_kb = core.stock_check_keyboard(0)
        await message.answer(sc_text, reply_markup=sc_kb)
        return

    if action == "Help":
        await message.answer(
            "❓ <b>How to use this bot</b>\n"
            "━━━━━━━━━━━━━━\n"
            "📞  <b>Get Number</b>   — claim a temporary number\n"
            "⏳  <b>Wait for OTP</b>  — auto-delivered on receipt\n"
            "💰  <b>Earn</b>          — every OTP credits your balance\n"
            "💸  <b>Withdraw</b>      — request a payout\n"
            "🧹  <b>Clear Prefix</b>  — release your active number\n"
            "📦  <b>Stock Check</b>   — live country stock\n"
            "━━━━━━━━━━━━━━\n"
            "💡 Keep the bot open for instant OTP delivery.",
            reply_markup=core.user_keyboard(),
        )
        return

    if action == "Withdraw":
        await _user_withdraw(message, s, u, user_id)
        return

    # ── Admin-side menu buttons ──────────────────────────────────
    if is_admin(user.id):
        if action == "Add Country":
            s.clear()
            s["awaiting_country"] = True
            await message.answer(
                "🌍 <b>Add Country</b>\n\n"
                "Send: <code>Name +DialCode [Prefix] [Service]</code>\n\n"
                "Examples:\n"
                "<code>INDIA +91 WS</code>\n"
                "<code>BANGLADESH +880 TG</code>\n"
                "<code>RUSSIA +7 9 WS</code>\n"
                "<code>KAZAKH +7 7 TG</code>\n"
                "<code>JAMAICA FAST +1 876 FB</code>\n"
                "<code>USA BUSINESS +1</code>\n\n"
                "✅ Service tokens: WS · TG · FB · IG · MS · G · APPLE · "
                "DISCORD · SIGNAL · SNAPCHAT · TIKTOK · TINDER · "
                "CHATGPT · VIBER\n"
                "✅ Long forms also work: WHATSAPP · TELEGRAM · FACEBOOK · …\n"
                "✅ Prefix and Service are both optional"
            )
            return

        if action == "Remove Country":
            await _admin_remove_country_menu(message)
            return

        if action == "Manage Numbers":
            await _admin_manage_numbers_menu(message)
            return

        if action == "Country Stats":
            await _admin_country_stats(message)
            return

        if action == "Bot Stats":
            await _admin_bot_stats(message)
            return

        if action == "Toggle Payout":
            db.CONFIG["payout_enabled"] = not db.CONFIG.get(
                "payout_enabled", True)
            db.save_config_key("payout_enabled")
            status = "✅ ON" if db.CONFIG["payout_enabled"] else "❌ OFF"
            await message.answer(f"🔄 Payouts: {status}",
                                 reply_markup=admin_kb(user.id))
            return

        if action == "Payouts":
            await _admin_payouts_list(message)
            return

        if action == "Broadcast":
            s.clear()
            s["awaiting_broadcast"] = True
            await message.answer(
                "📢 <b>Broadcast</b>\n\n"
                "Send the message you want to broadcast to all users.\n"
                "The bot will remain responsive during sending."
            )
            return

        if action == "Log Forwarding":
            await _admin_log_forwarding_menu(message, user.id)
            return

        if action == "Admin Management":
            await _admin_management(message, user.id)
            return

        if action == "Force Join":
            if not is_owner(user.id):
                await message.answer(
                    "❌This feature is <b>Owner-only</b>.",
                    reply_markup=admin_kb(user.id))
                return
            panel_text, panel_kb = core.fj_owner_panel_text(db.FORCE_JOIN)
            await message.answer(panel_text, reply_markup=panel_kb)
            return

        if action == "Owner":
            if not is_owner(user.id):
                await message.answer(
                    "❌ <b>Owner-only.</b>",
                    reply_markup=admin_kb(user.id, OWNER_ID))
                return
            await message.answer(
                "👑 <b>Owner Panel</b>\n"
                "━━━━━━━━━━━━━━\n"
                "📢  Broadcast\n"
                "👥  Admin Management\n"
                "📥  Import Users · 📤 Export Users\n"
                "📡  Log Forwarding · 🚫 Force Join\n"
                "━━━━━━━━━━━━━━\n"
                "Tap <b>⬅️ Back to Admin</b> to return.",
                reply_markup=core.owner_keyboard(),
            )
            return

        if action == "Import Users":
            if not is_owner(user.id):
                await message.answer(
                    "❌ <b>Owner-only.</b>",
                    reply_markup=admin_kb(user.id))
                return
            s.clear()
            s["awaiting_import_users"] = True
            await message.answer(
                "📥 <b>Import Users</b>\n"
                "━━━━━━━━━━━━━━\n"
                "Send a <code>.txt</code> or <code>.csv</code> file "
                "with user IDs.\n\n"
                "Both layouts are accepted:\n"
                "• one ID per line\n"
                "• comma-separated IDs\n\n"
                "Duplicates and invalid lines are ignored automatically.",
                reply_markup=core.owner_keyboard(),
            )
            return

        if action == "Export Users":
            if not is_owner(user.id):
                await message.answer(
                    "❌ <b>Owner-only.</b>",
                    reply_markup=admin_kb(user.id))
                return
            await _owner_export_users(message)
            return

        if action == "Back to Admin":
            await message.answer(
                "🔐 <b>Admin Panel</b>",
                reply_markup=admin_kb(user.id),
            )
            return


# ────────────────────────────────────────────────────────────────────
# Awaiting-state handlers
# ────────────────────────────────────────────────────────────────────
async def _handle_awaiting_country(message: Message, s: dict,
                                   text: str) -> None:
    s["awaiting_country"] = False
    storage_key, display_name, iso, dial_code, prefix, flag, service = (
        core.parse_country_input(text)
    )
    if not storage_key:
        s["awaiting_country"] = True
        await message.answer(
            "❌<b>Invalid format.</b>\n\n"
            "Use: <code>AnyName +DialCode [Prefix] [Service]</code>\n\n"
            "Examples:\n"
            "<code>INDIA +91 WS</code>\n"
            "<code>RUSSIA +7 9 WS</code>\n"
            "<code>KAZAKH +7 7 TG</code>\n"
            "<code>JAMAICA FAST +1 876 FB</code>\n"
            "<code>USA BUSINESS +1</code>\n\n"
            "Prefix and Service are both optional.\n"
            "Service tokens: WS · TG · FB · IG · MS · G · APPLE · DISCORD · "
            "SIGNAL · SNAPCHAT · TIKTOK · TINDER · CHATGPT · VIBER\n"
            "Long forms also work: WHATSAPP / TELEGRAM / FACEBOOK / etc."
        )
        return

    if storage_key in db.COUNTRIES["countries"]:
        storage_key = f"{storage_key}_{int(time.time())}"
    db.COUNTRIES["countries"][storage_key] = {
        "display_name":   display_name,
        "iso":            iso or "",
        "dial_code":      dial_code,
        "prefix":         prefix,
        "flag":           flag,
        "service":        service,
        "numbers":        [],
        "price":          DEFAULT_PRICE,
        "user_limit":     DEFAULT_NUMBER_COUNT,
        "total_otps":     0,
        "total_earnings": 0.0,
        "created_at":     str(datetime.datetime.utcnow()),
    }
    db.save_country(storage_key)
    log_message(f"Admin added country: {display_name} ({dial_code}) "
                f"{service or ''} -> {storage_key}")

    service_label = f" {service}" if service else ""
    await _maybe_log_forward(
        message.bot,
        f"⚠ Admin Action\n\n"
        f"Admin: @{message.from_user.username or ''} ({message.from_user.id})\n"
        f"Action: Added Country\n"
        f"Country: {display_name}{service_label}",
    )

    s["manage_country"] = storage_key
    header = f"{flag} <b>{display_name}</b> ({dial_code}){service_label}"
    await message.answer(
        f"✅Country added: {header}\n\n"
        f"<b>Managing: {header}</b>\n\n"
        f"📦Numbers: <b>0</b>\n"
        f"💰Price: <b>{DEFAULT_PRICE} rs</b>\n"
        f"👥Per User Limit: <b>{DEFAULT_NUMBER_COUNT}</b>",
        reply_markup=core.manage_country_kb(),
    )


async def _handle_awaiting_price(message: Message, s: dict,
                                 text: str) -> None:
    try:
        new_price = float(text)
    except ValueError:
        await message.answer("❌Invalid. Send a number (e.g. 0.5).")
        return
    c = s.get("manage_country")
    s["awaiting_price"] = False
    if not c:
        await message.answer("❌No country selected.",
                             reply_markup=admin_kb(message.from_user.id))
        return
    if c in db.COUNTRIES["countries"]:
        db.COUNTRIES["countries"][c]["price"] = new_price
        db.save_country(c)
        await message.answer(f"✅Price set to {new_price} rs for {c}",
                             reply_markup=admin_kb(message.from_user.id))
        log_message(f"Admin set price {new_price} for {c}")
    else:
        await message.answer(f"❌Country not found: {c}",
                             reply_markup=admin_kb(message.from_user.id))


async def _handle_awaiting_user_limit(message: Message, s: dict,
                                      text: str) -> None:
    try:
        new_limit = int(text)
    except ValueError:
        await message.answer("❌Invalid. Send a whole number (e.g. 4).")
        return
    if new_limit < 1 or new_limit > 20:
        await message.answer("❌Limit must be between 1 and 20.")
        return
    c = s.get("manage_country")
    s["awaiting_user_limit"] = False
    if not c:
        await message.answer("❌No country selected.",
                             reply_markup=admin_kb(message.from_user.id))
        return
    if c in db.COUNTRIES["countries"]:
        db.COUNTRIES["countries"][c]["user_limit"] = new_limit
        db.save_country(c)
        await message.answer(
            f"✅User limit set to <b>{new_limit}</b> per user for <b>{c}</b>.",
            reply_markup=admin_kb(message.from_user.id),
        )
        log_message(f"Admin set user_limit {new_limit} for {c}")
    else:
        await message.answer(f"❌Country not found: {c}",
                             reply_markup=admin_kb(message.from_user.id))


async def _handle_awaiting_user_limit_all(message: Message, s: dict,
                                          text: str) -> None:
    try:
        new_limit = int(text)
    except ValueError:
        await message.answer("❌Invalid. Send a whole number (e.g. 4).")
        return
    if new_limit < 1 or new_limit > 20:
        await message.answer("❌Limit must be between 1 and 20.")
        return
    for c_key in db.COUNTRIES["countries"]:
        db.COUNTRIES["countries"][c_key]["user_limit"] = new_limit
        db.save_country(c_key)
    s["awaiting_user_limit_all"] = False
    await message.answer(
        f"✅User limit updated to <b>{new_limit}</b> for <b>ALL</b> countries"
        f" ({len(db.COUNTRIES['countries'])} total).",
        reply_markup=admin_kb(message.from_user.id),
    )
    log_message(f"Admin set user_limit {new_limit} for ALL countries")


async def _handle_awaiting_log_group_id(message: Message, s: dict,
                                        text: str) -> None:
    s["awaiting_log_group_id"] = False
    try:
        group_id = int(text.strip())
    except ValueError:
        s["awaiting_log_group_id"] = True
        await message.answer(
            "❌Invalid. Send a valid group ID (e.g. -1003787023935).")
        return
    db.CONFIG["log_group_id"] = group_id
    db.save_config_key("log_group_id")
    state_lbl = ("🟢Running"
                 if db.CONFIG.get("log_forwarding_enabled", False)
                 else "🔴Stopped")
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔧Set Log Group ID",
                              callback_data="log_set_group")],
        [InlineKeyboardButton(text="▶ Start Log Forwarding",
                              callback_data="log_start")],
        [InlineKeyboardButton(text="⏹ Stop Log Forwarding",
                              callback_data="log_stop")],
        [InlineKeyboardButton(text="📊Status",
                              callback_data="log_status")],
        [InlineKeyboardButton(text="◀ Back", callback_data="back_admin")],
    ])
    await message.answer(
        f"📡<b>Log Forwarding</b>\n\n"
        f"Group: <code>{group_id}</code>\n"
        f"State: {state_lbl}",
        reply_markup=keyboard,
    )


async def _handle_awaiting_admin_id(message: Message, s: dict,
                                    text: str) -> None:
    s["awaiting_admin_id"] = False
    if not is_owner(message.from_user.id):
        return
    try:
        new_admin = int(text.strip())
    except ValueError:
        await message.answer("❌Send a valid numeric user ID.")
        return
    if new_admin in db.ADMIN_IDS or new_admin == OWNER_ID:
        await message.answer("⚠ User is already an admin/owner.")
        return
    db.ADMIN_IDS.append(new_admin)
    db.save_admins()
    log_message(f"Owner added admin {new_admin}")
    await message.answer(
        f"✅Admin <code>{new_admin}</code> added.",
        reply_markup=admin_kb(message.from_user.id),
    )


async def _handle_awaiting_fj_links(message: Message, s: dict,
                                    text: str, bot: Bot) -> None:
    s["awaiting_fj_links"] = False
    if not is_owner(message.from_user.id):
        return
    raw_inputs = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not raw_inputs:
        await message.answer("❌No inputs found.")
        return

    progress = await message.answer("⏳Resolving links...")
    added_now: list[dict] = []
    private_queue: list[dict] = []
    failed: list[tuple[str, str]] = []

    existing_ids = {c.get("chat_id") for c in db.FORCE_JOIN.get("chats", [])
                    if c.get("chat_id")}

    for raw in raw_inputs:
        try:
            entry = await _resolve_fj_input(raw, bot)
        except Exception as e:                         # noqa: BLE001
            failed.append((raw, str(e)))
            continue
        if entry is None:
            failed.append((raw, "unrecognised format"))
            continue
        if entry.get("_private_invite"):
            private_queue.append(entry)
            continue
        cid = entry.get("chat_id")
        if cid in existing_ids:
            failed.append((raw, "already configured"))
            continue
        existing_ids.add(cid)
        db.FORCE_JOIN.setdefault("chats", []).append({
            "chat_id":     cid,
            "title":       entry.get("title") or str(cid),
            "link":        entry.get("link") or "",
            "button_name": None,
        })
        added_now.append(entry)

    db.save_force_join()

    summary_lines: list[str] = []
    if added_now:
        summary_lines.append(
            "<b>Added:</b>\n" +
            "\n".join(f"✅<b>{e.get('title') or e.get('chat_id')}</b>"
                      for e in added_now)
        )
    if failed:
        summary_lines.append(
            "<b>Failed:</b>\n" +
            "\n".join(f"❌<code>{r}</code>\n  ↳ {reason}"
                      for r, reason in failed)
        )

    s["fj_private_queue"]    = private_queue
    s["fj_added_count"]      = len(added_now)

    if private_queue:
        first = private_queue[0]
        s["fj_current_private_idx"]  = 0
        s["awaiting_fj_private_id"]  = True
        await progress.edit_text(
            "\n\n".join(summary_lines) if summary_lines else " "
        )
        await message.answer(
            f"🔒<b>Private Group Detected</b>\n\n"
            f"Link: <code>{first['link']}</code>\n\n"
            f"To verify membership, the bot needs the <b>chat ID</b>.\n\n"
            f"Steps to get the chat ID:\n"
            f"1. Forward a message from the group to @userinfobot\n"
            f"2. Or use @getidsbot inside the group\n\n"
            f"Send the chat ID (e.g. <code>-1003879732518</code>):\n"
            f"<i>({len(private_queue)} private group(s) remaining)</i>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⏭ Skip This Group",
                                      callback_data="fj_skip_private")],
                [InlineKeyboardButton(text="❌Cancel All",
                                      callback_data="fj_cancel_links")],
            ]),
        )
        return

    total_added = len(added_now)
    summary_text = ("\n\n".join(summary_lines)
                    if summary_lines else "No new chats added.")
    await progress.edit_text(
        f"📋<b>Link Resolution Report</b>\n\n{summary_text}",
    )
    if total_added > 0:
        await _fj_ask_button_names(message, s, total_added)
    else:
        panel_text, panel_kb = core.fj_owner_panel_text(db.FORCE_JOIN)
        await message.answer(panel_text, reply_markup=panel_kb)


async def _handle_awaiting_fj_private_id(message: Message, s: dict,
                                         text: str) -> None:
    if not is_owner(message.from_user.id):
        return
    stripped = text.strip()
    if re.match(r"^-\d{5,}$", stripped):
        cid = int(stripped)
    elif re.match(r"^\+\d{5,}$", stripped):
        cid = -int(stripped[1:])
    else:
        await message.answer(
            "❌<b>Invalid chat ID.</b>\n\n"
            "Send a valid negative chat ID, e.g. <code>-1003879732518</code>\n"
            "Or press <b>Skip</b> to skip this group.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⏭ Skip This Group",
                                      callback_data="fj_skip_private")],
                [InlineKeyboardButton(text="❌Cancel All",
                                      callback_data="fj_cancel_links")],
            ]),
        )
        return

    s["awaiting_fj_private_id"] = False
    queue = s.get("fj_private_queue", [])
    idx = s.get("fj_current_private_idx", 0)
    current = queue[idx] if idx < len(queue) else None

    if current:
        link = current["link"]
        hash_part = re.search(r"/\+([A-Za-z0-9_-]+)", link)
        short = hash_part.group(1)[:8] if hash_part else "private"
        existing_ids = {c.get("chat_id") for c in db.FORCE_JOIN.get("chats", [])
                        if c.get("chat_id")}
        if cid in existing_ids:
            await message.answer(
                f"⚠ Chat ID <code>{cid}</code> is already in the list. "
                f"Skipping."
            )
        else:
            db.FORCE_JOIN.setdefault("chats", []).append({
                "chat_id":     cid,
                "title":       f"Private Group ({short}…)",
                "link":        link,
                "button_name": None,
            })
            db.save_force_join()
            s["fj_added_count"] = s.get("fj_added_count", 0) + 1
            await message.answer(
                f"✅Added private group with chat ID <code>{cid}</code>."
            )

    await _fj_process_next_private(message, s, idx + 1)


async def _fj_process_next_private(message: Message, s: dict,
                                   next_idx: int) -> None:
    queue = s.get("fj_private_queue", [])
    if next_idx < len(queue):
        s["fj_current_private_idx"] = next_idx
        s["awaiting_fj_private_id"] = True
        first = queue[next_idx]
        await message.answer(
            f"🔒<b>Next Private Group</b>\n\n"
            f"Link: <code>{first['link']}</code>\n\n"
            f"Send the chat ID for this group:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⏭ Skip This Group",
                                      callback_data="fj_skip_private")],
                [InlineKeyboardButton(text="❌Cancel All",
                                      callback_data="fj_cancel_links")],
            ]),
        )
        return
    total_added = s.pop("fj_added_count", 0)
    s.pop("fj_private_queue", None)
    s.pop("fj_current_private_idx", None)
    if total_added > 0:
        await _fj_ask_button_names(message, s, total_added)
    else:
        panel_text, panel_kb = core.fj_owner_panel_text(db.FORCE_JOIN)
        await message.answer(panel_text, reply_markup=panel_kb)


async def _fj_ask_button_names(message: Message, s: dict, count: int) -> None:
    s["fj_pending_names_count"] = count
    s["awaiting_fj_names"] = True
    names_example = "\n".join(f"Group {i+1} Name" for i in range(min(count, 3)))
    suffix = "…" if count > 3 else ""
    await message.answer(
        f"✏ <b>Step — Button Names</b>\n\n"
        f"Send <b>{count}</b> button name(s), one per line.\n"
        f"These are the labels shown to users on the join buttons.\n\n"
        f"Example:\n<code>{names_example}{suffix}</code>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏭ Skip — Use Default Names",
                                  callback_data="fj_skip_names")],
        ]),
    )


async def _handle_awaiting_fj_names(message: Message, s: dict,
                                    text: str) -> None:
    if not is_owner(message.from_user.id):
        return
    s["awaiting_fj_names"] = False
    count = s.pop("fj_pending_names_count", 0)
    raw_names = [n.strip() for n in text.splitlines() if n.strip()]
    chats = db.FORCE_JOIN.get("chats", [])
    start_idx = len(chats) - count
    for i in range(count):
        idx = start_idx + i
        if idx < len(chats):
            custom = raw_names[i] if i < len(raw_names) else f"Join Group {idx+1}"
            chats[idx]["button_name"] = custom
    db.save_force_join()
    panel_text, panel_kb = core.fj_owner_panel_text(db.FORCE_JOIN)
    names_set = "\n".join(
        f"• <b>{chats[start_idx + i].get('button_name', '?')}</b> → "
        f"{chats[start_idx + i].get('title', '?')}"
        for i in range(count) if start_idx + i < len(chats)
    )
    await message.answer(
        f"✅<b>Button names saved!</b>\n\n{names_set}\n\n"
        f"Total chats configured: <b>{len(chats)}</b>"
    )
    await message.answer(panel_text, reply_markup=panel_kb)


async def _handle_awaiting_text_numbers(message: Message, s: dict,
                                        text: str) -> None:
    lines = text.splitlines()
    valid_nums = [
        ln.strip() for ln in lines
        if re.match(r"^\+?\d{6,20}$", ln.strip())
    ]
    if not valid_nums:
        await message.answer(
            "⚠ No valid numbers found in your text.\n"
            "Format: one number per line "
            "(e.g. <code>+2250767201995</code>)"
        )
        return
    # Auto-finalize: text pastes commit immediately so the admin
    # sees the success card without an extra DONE click.  Buffer is
    # accumulated only across multiple paste-batches in the same
    # session (kept here for backwards compatibility).
    buf = s.setdefault("upload_buffer", [])
    buf.extend(valid_nums)
    await _commit_uploaded_numbers(message, s)


# ────────────────────────────────────────────────────────────────────
# Owner: Import Users / Export Users
# ────────────────────────────────────────────────────────────────────
def _parse_user_ids_blob(blob: str) -> tuple[list[int], int]:
    """Parse a raw text blob of user IDs.

    Accepts both layouts simultaneously (mixed lines + commas):
      * one ID per line
      * comma-separated IDs on one line
      * mixed (one line: ``1,2,3``; next line: ``4``; …)

    Returns ``(valid_ids_unique, invalid_count)``.
    """
    valid: list[int] = []
    seen: set[int] = set()
    invalid = 0
    for raw_token in re.split(r"[,\s;]+", blob):
        tok = raw_token.strip()
        if not tok:
            continue
        try:
            uid = int(tok)
        except ValueError:
            invalid += 1
            continue
        if uid in seen:
            continue
        seen.add(uid)
        valid.append(uid)
    return valid, invalid


async def _handle_import_users_file(message: Message, s: dict,
                                    bot: Bot) -> None:
    """Owner sent a .txt / .csv file after tapping ``📥 Import Users``."""
    s.pop("awaiting_import_users", None)
    doc = message.document
    if doc is None:
        await message.answer(
            "❌ Please send a <code>.txt</code> or <code>.csv</code> "
            "file containing user IDs.",
            reply_markup=core.owner_keyboard(),
        )
        return

    name = (doc.file_name or "").lower()
    if not (name.endswith(".txt") or name.endswith(".csv")):
        await message.answer(
            "❌ Unsupported file type. Send a <code>.txt</code> or "
            "<code>.csv</code> file.",
            reply_markup=core.owner_keyboard(),
        )
        return

    progress = await message.answer(
        "📥 Downloading file…",
        reply_markup=core.owner_keyboard(),
    )

    try:
        buf = io.BytesIO()
        await bot.download(doc.file_id, destination=buf)
        try:
            blob = buf.getvalue().decode("utf-8", errors="ignore")
        finally:
            buf.close()
    except Exception as e:                          # noqa: BLE001
        await progress.edit_text(f"❌ Failed to download file: {e}")
        return

    if not blob.strip():
        await progress.edit_text("❌ File is empty.")
        return

    await progress.edit_text("⏳ Parsing user IDs…")
    valid_ids, invalid_count = _parse_user_ids_blob(blob)

    if not valid_ids:
        await progress.edit_text(
            f"⚠ No valid user IDs found.\n"
            f"Invalid tokens skipped: <b>{invalid_count}</b>")
        return

    await progress.edit_text(
        f"⏳ Importing <b>{len(valid_ids):,}</b> IDs into PostgreSQL…")
    inserted, duplicates = await db.bulk_import_users(valid_ids)

    await progress.edit_text(
        "📥 <b>Import Finished</b>\n"
        "━━━━━━━━━━━━━━\n"
        f"✅ Imported:   <b>{inserted:,}</b>\n"
        f"♻️ Duplicates: <b>{duplicates:,}</b>\n"
        f"⚠ Invalid:    <b>{invalid_count:,}</b>\n"
        f"📦 Total now:  <b>{len(db.USERS):,}</b>",
    )
    log_message(
        f"Owner imported {inserted} users "
        f"({duplicates} dup, {invalid_count} invalid)"
    )


async def _owner_export_users(message: Message) -> None:
    """Owner tapped ``📤 Export Users``: dump every user_id to a .txt
    document (one ID per line) and send it back as a Telegram file.
    """
    progress = await message.answer(
        "⏳ Exporting users…",
        reply_markup=core.owner_keyboard(),
    )
    try:
        ids = await db.export_user_ids()
    except Exception as e:                          # noqa: BLE001
        await progress.edit_text(f"❌ Export failed: {e}")
        return

    if not ids:
        await progress.edit_text("📦 No users to export.")
        return

    blob = ("\n".join(str(uid) for uid in ids)).encode("utf-8")
    fname = f"users_{datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.txt"
    file = BufferedInputFile(blob, filename=fname)

    await message.answer_document(
        file,
        caption=(
            "📤 <b>Users Export</b>\n"
            f"👥 Total: <b>{len(ids):,}</b>"
        ),
    )
    try:
        await progress.delete()
    except Exception:                               # noqa: BLE001
        pass
    log_message(f"Owner exported {len(ids)} users")


async def _handle_awaiting_broadcast(message: Message, s: dict,
                                     text: str) -> None:
    s["awaiting_broadcast"] = False
    msg = text
    if not msg:
        await message.answer("❌Empty message.",
                             reply_markup=admin_kb(message.from_user.id))
        return
    user_count = len(db.USERS)
    if not user_count:
        await message.answer("No users to broadcast to.",
                             reply_markup=admin_kb(message.from_user.id))
        return
    s["broadcast_msg"] = msg
    confirm_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Confirm",
                              callback_data="broadcast_confirm",
                              style="success"),
         InlineKeyboardButton(text="❌ Cancel",
                              callback_data="broadcast_cancel_cb",
                              style="danger")],
    ])
    await message.answer(
        f"📢 <b>Broadcast Preview</b>\n\n"
        f"👥 Users: <b>{user_count:,}</b>\n\n"
        f"<b>Message:</b>\n<i>{msg[:300]}"
        f"{'…' if len(msg) > 300 else ''}</i>\n\n"
        f"Send this to everyone?",
        reply_markup=confirm_kb,
    )


async def _handle_awaiting_daily_date(message: Message, s: dict,
                                      text: str) -> None:
    s["awaiting_daily_date"] = False
    date = core.parse_date_input(text)
    if not date:
        await message.answer("❌Invalid date. Try YYYY-MM-DD or DD-MM-YYYY.")
        return
    today_str = core._today_str()
    if date == today_str:
        data = db.DAILY_STATS.get("today", {})
    else:
        data = db.DAILY_STATS.get("history", {}).get(date)
    if not data:
        await message.answer(
            f"📭No data for <b>{date}</b>.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙Back", callback_data="ds_menu")],
            ]),
        )
        return
    await message.answer(
        core.format_daily_stats(date, data),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙Back", callback_data="ds_menu")],
        ]),
    )


async def _handle_awaiting_daily_range(message: Message, s: dict,
                                       text: str) -> None:
    s["awaiting_daily_range"] = False
    start, end = core.parse_date_range_input(text)
    if not start or not end:
        await message.answer(
            "❌Invalid range. Try `DD-MM-YYYY to DD-MM-YYYY`.")
        return
    await message.answer(
        core.format_range_stats(start, end),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙Back", callback_data="ds_menu")],
        ]),
    )


# ────────────────────────────────────────────────────────────────────
# User flow: Get Number / Clear / Balance / Withdraw
# ────────────────────────────────────────────────────────────────────
async def _user_get_number(message: Message, u: dict) -> None:
    if u.get("awaiting_otp") and u.get("current_number"):
        c_key = u.get("current_country")
        info = db.COUNTRIES["countries"].get(c_key, {}) if c_key else {}
        panel = core.build_active_number_panel(
            country_key=c_key,
            info=info,
            number=u["current_number"],
            numbers_extra=u.get("current_numbers") or [],
        )
        await message.answer(
            panel,
            reply_markup=core.active_number_buttons(
                OTP_VIEW_URL,
                current_number=u["current_number"],
                numbers=u.get("current_numbers") or [],
                iso=info.get("iso") if isinstance(info, dict) else None,
            ),
        )
        return
    text, kb = _build_country_picker("📞 <b>Choose a country to get a number:</b>")
    if kb is None:
        await message.answer("📦 No numbers available right now.",
                             reply_markup=core.user_keyboard())
        return
    await message.answer(text, reply_markup=kb)


def _build_country_picker(header: str
                          ) -> tuple[str, InlineKeyboardMarkup | None]:
    """Build the 2-col country picker used by Get Number / Change
    Country.  Returns (text, kb) — kb is None when there's nothing
    in stock anywhere.
    """
    sorted_countries = sorted(
        db.COUNTRIES["countries"].items(),
        key=lambda x: x[1].get("display_name", x[0].upper()),
    )
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    any_avail = False
    for c, info in sorted_countries:
        if not isinstance(info, dict):
            continue
        if not info.get("numbers"):
            continue
        any_avail = True
        row.append(core.country_button(c, info))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    if not any_avail:
        return header, None
    rows.append([
        InlineKeyboardButton(text="📦 Stock Check",
                             callback_data="stock_p_0",
                             style="primary"),
        InlineKeyboardButton(text="⬅️ Back",
                             callback_data="back_user",
                             style="primary"),
    ])
    return header, InlineKeyboardMarkup(inline_keyboard=rows)


async def _user_clear_prefix(message: Message, u: dict) -> None:
    if u.get("current_number"):
        old_country = u.get("current_country")
        old_nums = list(u.get("current_numbers") or [])
        if not old_nums and u.get("current_number"):
            old_nums = [u["current_number"]]
        if old_country and old_country in db.COUNTRIES["countries"] and old_nums:
            await db.release_numbers(old_country, old_nums)
        u["current_number"] = None
        u["current_numbers"] = []
        u["current_country"] = None
        u["awaiting_otp"] = False
        db.save_user(str(message.from_user.id))
        await message.answer(
            "🧹 Number cleared! You can get a new one.",
            reply_markup=core.user_keyboard(),
        )
    else:
        await message.answer("ℹ No active number to clear.",
                             reply_markup=core.user_keyboard())


async def _user_balance(message: Message, u: dict) -> None:
    bal = u.get("balance", 0)
    otps_count = u.get("otps", 0)
    current_num = u.get("current_number") or "None"
    uname = u.get("username") or "N/A"
    await message.answer(
        f"💰<b>Your Balance</b>\n\n"
        f"👤User: @{uname}\n"
        f"💵Balance: <b>{bal} rs</b>\n"
        f"📦Total OTPs: <b>{otps_count}</b>\n"
        f"📞Current Number: <code>{current_num}</code>",
        reply_markup=core.user_keyboard(),
    )


async def _user_withdraw(message: Message, s: dict, u: dict,
                         user_id: str) -> None:
    if not db.CONFIG.get("payout_enabled", True):
        await message.answer("❌Withdrawals are currently disabled.",
                             reply_markup=core.user_keyboard())
        return
    bal = float(u.get("balance", 0))
    if bal < MIN_PAYOUT:
        need = round(MIN_PAYOUT - bal, 2)
        await message.answer(
            f"⚠ <b>Low Balance!</b>\n\n"
            f"💰Your balance: <b>{bal} rs</b>\n"
            f"📌Minimum to withdraw: <b>{MIN_PAYOUT} rs</b>\n\n"
            f"You need <b>{need} rs</b> more.",
            reply_markup=core.user_keyboard(),
        )
        return
    pending = any(p.get("user") == user_id and p.get("status") == "pending"
                  for p in db.PAYOUTS)
    if pending:
        await message.answer(
            "⚠ You already have a pending payout request.",
            reply_markup=core.user_keyboard(),
        )
        return
    s["awaiting_payout_step"] = "amount"
    await message.answer(
        f"💰Enter payout amount\n\n"
        f"Balance: <b>{bal} rs</b>\n"
        f"Min: <b>{MIN_PAYOUT} rs</b> | Max: <b>{bal} rs</b>"
    )


async def _handle_payout_step(message: Message, s: dict, text: str,
                              u: dict, step: str) -> None:
    if step == "amount":
        try:
            amount = int(text)
        except ValueError:
            await message.answer(
                f"❌Invalid. Enter a number (Max {u.get('balance',0)} rs)")
            return
        if amount < MIN_PAYOUT or amount > u.get("balance", 0):
            await message.answer(
                f"❌Enter between {MIN_PAYOUT} and {u.get('balance',0)} rs")
            return
        s["payout_amount"] = amount
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Binance",
                                  callback_data="payout_method_binance")],
            [InlineKeyboardButton(text="Rocket",
                                  callback_data="payout_method_rocket")],
        ])
        await message.answer("Choose payout method:", reply_markup=keyboard)
        s["awaiting_payout_step"] = "method"
    elif step == "details":
        s["payout_details"] = text
        s["awaiting_payout_step"] = None
        amount = s["payout_amount"]
        method = s["payout_method"]
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Confirm",
                                  callback_data="payout_confirm"),
             InlineKeyboardButton(text="Edit",
                                  callback_data="payout_edit"),
             InlineKeyboardButton(text="Cancel",
                                  callback_data="payout_cancel")],
        ])
        await message.answer(
            f"Payout Preview:\nAmount: {amount} rs\nMethod: {method}\n"
            f"Details: {text}",
            reply_markup=keyboard,
        )


# ────────────────────────────────────────────────────────────────────
# Admin menu actions
# ────────────────────────────────────────────────────────────────────
async def _admin_remove_country_menu(message: Message) -> None:
    buttons: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for c, info in db.COUNTRIES["countries"].items():
        flag = info.get("flag", "")
        display = info.get("display_name", c.upper())
        dial = info.get("dial_code", "")
        service = (info.get("service") or "").strip().upper()
        suffix = f" {service}" if service else ""
        emoji_id = core.country_emoji_id(info.get("iso", ""))
        row.append(InlineKeyboardButton(
            text=f"{flag} {display} ({dial}){suffix}",
            callback_data=f"del_{c}",
            style="danger",
            icon_custom_emoji_id=emoji_id,
        ))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    if not buttons:
        await message.answer("No countries.",
                             reply_markup=admin_kb(message.from_user.id))
        return
    buttons.append([InlineKeyboardButton(text="⬅️ Back",
                                         callback_data="back_admin",
                                         style="primary")])
    await message.answer("❌ <b>Select a country to remove:</b>",
                         reply_markup=InlineKeyboardMarkup(
                             inline_keyboard=buttons))


async def _admin_manage_numbers_menu(message: Message) -> None:
    buttons: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for c, info in db.COUNTRIES["countries"].items():
        flag = info.get("flag", "")
        display = info.get("display_name", c.upper())
        service = (info.get("service") or "").strip().upper()
        suffix = f" {service}" if service else ""
        cnt = len(info.get("numbers", []))
        emoji_id = core.country_emoji_id(info.get("iso", ""))
        row.append(InlineKeyboardButton(
            text=f"{flag} {display}{suffix} · {cnt}",
            callback_data=f"manage_{c}",
            style=core.stock_button_style(cnt),
            icon_custom_emoji_id=emoji_id,
        ))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    if not buttons:
        await message.answer(
            "No countries. Add one first.",
            reply_markup=admin_kb(message.from_user.id))
        return
    buttons.append([InlineKeyboardButton(text="⬅️ Back",
                                         callback_data="back_admin",
                                         style="primary")])
    await message.answer("Select country to manage:",
                         reply_markup=InlineKeyboardMarkup(
                             inline_keyboard=buttons))


async def _admin_country_stats(message: Message) -> None:
    txt = "<b>📊Numbers by Country</b>\n\n"
    for c, info in db.COUNTRIES["countries"].items():
        cnt = len(info.get("numbers", []))
        price = info.get("price", DEFAULT_PRICE)
        flag = info.get("flag", "")
        display = info.get("display_name", c.upper())
        dial = info.get("dial_code", "")
        txt += (f"{flag} {display} ({dial}): <b>{cnt}</b> numbers | "
                f"💰<b>{price} rs</b>\n")
    if not db.COUNTRIES["countries"]:
        txt += "No countries added yet."
    await message.answer(txt, reply_markup=admin_kb(message.from_user.id))


async def _admin_bot_stats(message: Message) -> None:
    total_users = len(db.USERS)
    total_balance = round(sum(float(v.get("balance", 0))
                              for v in db.USERS.values()), 2)
    total_otps = sum(int(v.get("otps", 0)) for v in db.USERS.values())
    txt = (
        f"<b>🤖Bot Statistics</b>\n\n"
        f"👥Total Users: <b>{total_users}</b>\n"
        f"💰Total Balance: <b>{total_balance} rs</b>\n"
        f"📦Total OTPs: <b>{total_otps}</b>\n\n"
        f"━━━━━━━━━━━━━━\n"
        f"📊OTPs By Country\n"
        f"━━━━━━━━━━━━━━\n\n"
    )
    for c_key, c_info in db.COUNTRIES["countries"].items():
        c_flag = c_info.get("flag", core.GLOBE)
        c_display = c_info.get("display_name", c_key.upper())
        c_dial = c_info.get("dial_code", "")
        c_otps = c_info.get("total_otps", 0)
        c_nums = len(c_info.get("numbers", []))
        c_price = c_info.get("price", DEFAULT_PRICE)
        txt += (
            f"{c_flag} {c_display} ({c_dial})\n"
            f"• OTPs: {c_otps}\n"
            f"• Active Numbers: {c_nums}\n"
            f"• Price: {c_price} rs\n\n"
        )
    if not db.COUNTRIES["countries"]:
        txt += "No countries added yet.\n"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊Detailed Country Stats",
                              callback_data="detailed_country_stats")],
        [InlineKeyboardButton(text="📅Daily Statistics",
                              callback_data="ds_menu")],
        [InlineKeyboardButton(text="🔙Back", callback_data="back_admin")],
    ])
    await message.answer(txt, reply_markup=keyboard)


async def _admin_payouts_list(message: Message) -> None:
    pending_payouts = [p for p in db.PAYOUTS
                       if p.get("status") == "pending"]
    if not pending_payouts:
        await message.answer(
            "📭No pending payout requests.",
            reply_markup=admin_kb(message.from_user.id))
        return
    await message.answer(
        f"💳Pending Payouts: <b>{len(pending_payouts)}</b>",
        reply_markup=admin_kb(message.from_user.id),
    )
    for p in pending_payouts:
        uid = p.get("user", "?")
        u_record = db.USERS.get(str(uid), {})
        uname = u_record.get("username") or "N/A"
        txt = (
            f"<b>💳Payout Request</b>\n"
            f"👤User: <code>{uid}</code> (@{uname})\n"
            f"💵Amount: <b>{p.get('amount',0)} rs</b>\n"
            f"📌Method: {p.get('method','N/A')}\n"
            f"📝Details: <code>{p.get('details','')}</code>"
        )
        btns = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅Done",
                                 callback_data=f"payout_done_{p['id']}"),
            InlineKeyboardButton(text="❌Decline",
                                 callback_data=f"payout_decline_{p['id']}"),
        ]])
        await message.answer(txt, reply_markup=btns)


async def _admin_log_forwarding_menu(message: Message,
                                     user_id: int) -> None:
    if not is_owner(user_id):
        await message.answer("❌This feature is <b>Owner-only</b>.",
                             reply_markup=admin_kb(user_id))
        return
    group_id = db.CONFIG.get("log_group_id", "Not Set")
    forwarding = db.CONFIG.get("log_forwarding_enabled", False)
    state_lbl = "🟢Running" if forwarding else "🔴Stopped"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔧Set Log Group ID",
                              callback_data="log_set_group")],
        [InlineKeyboardButton(text="▶ Start Log Forwarding",
                              callback_data="log_start")],
        [InlineKeyboardButton(text="⏹ Stop Log Forwarding",
                              callback_data="log_stop")],
        [InlineKeyboardButton(text="📊Status",
                              callback_data="log_status")],
        [InlineKeyboardButton(text="◀ Back",
                              callback_data="back_admin")],
    ])
    await message.answer(
        f"📡<b>Log Forwarding</b>\n\n"
        f"Group: <code>{group_id}</code>\n"
        f"State: {state_lbl}",
        reply_markup=keyboard,
    )


async def _admin_management(message: Message, user_id: int) -> None:
    if not is_owner(user_id):
        await message.answer("❌This feature is <b>Owner-only</b>.",
                             reply_markup=admin_kb(user_id))
        return
    buttons: list[list[InlineKeyboardButton]] = []
    for aid in db.ADMIN_IDS:
        aname = db.USERS.get(str(aid), {}).get("username") or "Unknown"
        buttons.append([
            InlineKeyboardButton(text=f"👤@{aname} ({aid})",
                                 callback_data="noop"),
            InlineKeyboardButton(text="❌Remove",
                                 callback_data=f"admin_remove_{aid}"),
        ])
    buttons.append([InlineKeyboardButton(text="➕Add Admin",
                                         callback_data="admin_add")])
    buttons.append([InlineKeyboardButton(text="🔙Back",
                                         callback_data="back_admin")])
    admin_text = (
        "👥<b>Admin Management</b>\n\n"
        f"👑Owner: <code>{OWNER_ID}</code>\n"
    )
    if db.ADMIN_IDS:
        admin_text += "\n<b>Current Admins:</b>\n"
        for aid in db.ADMIN_IDS:
            aname = db.USERS.get(str(aid), {}).get("username") or "Unknown"
            admin_text += f"👤@{aname}: <code>{aid}</code>\n"
    else:
        admin_text += "\nNo admins added yet.\n"
    await message.answer(admin_text,
                         reply_markup=InlineKeyboardMarkup(
                             inline_keyboard=buttons))


async def _maybe_log_forward(bot: Bot, txt: str) -> None:
    if not db.CONFIG.get("log_forwarding_enabled", False):
        return
    gid = db.CONFIG.get("log_group_id")
    if not gid:
        return
    try:
        await bot.send_message(chat_id=gid, text=txt)
    except Exception:                          # noqa: BLE001
        pass


# ════════════════════════════════════════════════════════════════════
#                        Callback handler
# ════════════════════════════════════════════════════════════════════
async def _fj_anti_bypass(query: CallbackQuery, bot: Bot) -> bool:
    """Returns True if the callback is allowed to proceed."""
    data = query.data or ""
    passthrough = data.startswith("fj_") or data == "back_user"
    if passthrough or is_admin(query.from_user.id):
        return True
    all_joined, not_joined = await check_force_join(query.from_user.id, bot)
    if all_joined:
        return True
    text, kb = core.force_join_user_text(_missing_chat_entries(not_joined))
    await query.answer("⚠ You must join all required groups first.",
                       show_alert=True)
    try:
        await query.message.edit_text(text, reply_markup=kb)
    except Exception:                           # noqa: BLE001
        pass
    return False


@dp.callback_query()
async def on_callback(query: CallbackQuery, bot: Bot) -> None:
    try:
        await query.answer()
    except Exception:                           # noqa: BLE001
        pass

    if not await _fj_anti_bypass(query, bot):
        return

    data = query.data or ""
    user_id = str(query.from_user.id)
    user = query.from_user
    u = core.ensure_user(user_id, user.username)
    s = state(user.id)

    if data.startswith("take_"):
        await _cb_take(query, u, data)
    elif data == "user_change_number":
        await _cb_user_change_number(query, u)
    elif data == "user_change_country":
        await _cb_user_change_country(query)
    elif data == "user_cancel_number":
        await _cb_user_cancel_number(query, u)
    elif data == "user_get_number":
        text_p, kb_p = _build_country_picker(
            "📞 <b>Choose a country to get a number:</b>")
        if kb_p is None:
            await _safe_edit(query, "📦 No numbers available right now.")
        else:
            await _safe_edit(query, text_p, reply_markup=kb_p)
    elif data.startswith("stock_p_"):
        try:
            page = int(data.replace("stock_p_", "", 1))
        except ValueError:
            page = 0
        sc_text, sc_kb = core.stock_check_keyboard(page)
        await _safe_edit(query, sc_text, reply_markup=sc_kb)
    elif data == "user_back":
        await _safe_edit(query, "Use buttons below 👇")
    elif data == "back_user":
        clear_state(user.id)
        await _safe_edit(query, "Use buttons below 👇")
    elif data == "back_admin":
        clear_state(user.id)
        await _safe_edit(query, "🔐Returned to Admin Panel.")
    elif data.startswith("payout_method_"):
        s["payout_method"] = data.replace("payout_method_", "")
        s["awaiting_payout_step"] = "details"
        await _safe_edit(query, f"Enter your {s['payout_method']} ID/number:")
    elif data == "payout_confirm":
        await _cb_payout_confirm(query, s, user_id, user.username, bot)
    elif data == "payout_edit":
        s["awaiting_payout_step"] = "amount"
        await _safe_edit(query, "Enter new payout amount:")
    elif data == "payout_cancel":
        s.pop("awaiting_payout_step", None)
        await _safe_edit(query, "Payout cancelled.")
    elif data == "fj_check":
        await _cb_fj_check(query, bot)
    elif data == "fj_set_links":
        await _cb_fj_set_links(query, s)
    elif data == "fj_skip_names":
        await _cb_fj_skip_names(query, s)
    elif data == "fj_skip_private":
        await _cb_fj_skip_private(query, s)
    elif data == "fj_cancel_links":
        await _cb_fj_cancel_links(query, s)
    elif data == "fj_toggle":
        await _cb_fj_toggle(query)
    elif data == "fj_view_groups":
        await _cb_fj_view_groups(query)
    elif data == "fj_remove_menu":
        await _cb_fj_remove_menu(query)
    elif data.startswith("fj_rem_"):
        await _cb_fj_rem(query, data)
    elif data.startswith("fj_confirm_rem_"):
        await _cb_fj_confirm_rem(query, data)
    elif data == "fj_back_panel":
        if not is_owner(user.id):
            return
        panel_text, panel_kb = core.fj_owner_panel_text(db.FORCE_JOIN)
        await _safe_edit(query, panel_text, reply_markup=panel_kb)
    elif data == "fj_scan":
        await _cb_fj_scan(query)
    elif data.startswith("fj_add_known_"):
        await _cb_fj_add_known(query, data)
    elif data.startswith("del_"):
        await _cb_del_country(query, data)
    elif data.startswith("manage_"):
        await _cb_manage_country(query, s, data)
    elif data == "upload_numbers":
        s["awaiting_file"] = True
        s["upload_buffer"] = []
        s["upload_file_count"] = 0
        await _safe_edit(
            query,
            "📤Send the numbers as a <code>.txt</code> file or paste them as "
            "text (one per line)."
        )
    elif data == "upload_done":
        await _cb_upload_done(query, s)
    elif data == "upload_cancel":
        s.pop("awaiting_file", None)
        s.pop("upload_buffer", None)
        s.pop("upload_file_count", None)
        await _safe_edit(query, "Upload cancelled.")
    elif data == "clear_numbers":
        await _cb_clear_numbers(query, s)
    elif data == "confirm_clear_numbers":
        await _cb_confirm_clear_numbers(query, s)
    elif data == "cancel_clear_numbers":
        await _cb_cancel_clear_numbers(query, s)
    elif data == "broadcast_confirm":
        await _cb_broadcast_confirm(query, s, bot)
    elif data == "broadcast_cancel_cb":
        s.pop("broadcast_msg", None)
        s.pop("broadcast_user_ids", None)
        await _safe_edit(query, "❌Broadcast cancelled.")
    elif data == "manage_back":
        await _cb_manage_back(query, s)
    elif data == "admin_set_price":
        s["awaiting_price"] = True
        await _safe_edit(query, "💲Send the new price (e.g. <code>0.5</code>):")
    elif data == "admin_set_user_limit":
        await _cb_set_user_limit(query, s)
    elif data == "set_limit_this_country":
        s["awaiting_user_limit"] = True
        await _safe_edit(query, "Send the new per-user number limit:")
    elif data == "set_limit_all_countries":
        s["awaiting_user_limit_all"] = True
        await _safe_edit(query,
                         "Send the new per-user limit (applies to ALL countries):")
    elif data == "country_performance":
        await _cb_country_performance(query, s)
    elif data == "detailed_country_stats":
        await _cb_detailed_country_stats(query)
    elif data == "log_set_group":
        if not is_owner(user.id):
            return
        s["awaiting_log_group_id"] = True
        await _safe_edit(query, "Send the group/channel ID to forward logs to:")
    elif data == "log_start":
        if not is_owner(user.id):
            return
        db.CONFIG["log_forwarding_enabled"] = True
        db.save_config_key("log_forwarding_enabled")
        await _safe_edit(query, "▶ Log forwarding <b>started</b>.")
    elif data == "log_stop":
        if not is_owner(user.id):
            return
        db.CONFIG["log_forwarding_enabled"] = False
        db.save_config_key("log_forwarding_enabled")
        await _safe_edit(query, "⏹ Log forwarding <b>stopped</b>.")
    elif data == "log_status":
        if not is_owner(user.id):
            return
        await _safe_edit(
            query,
            f"📊Log forwarding: "
            f"{'🟢ON' if db.CONFIG.get('log_forwarding_enabled') else '🔴OFF'}\n"
            f"Group: <code>{db.CONFIG.get('log_group_id', 'Not Set')}</code>"
        )
    elif data == "admin_add":
        if not is_owner(user.id):
            return
        s["awaiting_admin_id"] = True
        await _safe_edit(query, "Send the user ID to add as admin:")
    elif data.startswith("admin_remove_"):
        await _cb_admin_remove(query, data)
    elif data.startswith("payout_done_"):
        await _cb_payout_done(query, data, bot)
    elif data.startswith("payout_decline_"):
        await _cb_payout_decline(query, data, bot)
    elif data.startswith("confirm_delete_country_"):
        await _cb_confirm_delete_country(query, data)
    elif data == "cancel_delete_country":
        await _safe_edit(query, "Cancelled.")
    elif data == "ds_menu":
        await _cb_ds_menu(query)
    elif data == "ds_today":
        await _cb_ds_today(query)
    elif data == "ds_yesterday":
        await _cb_ds_yesterday(query)
    elif data == "ds_search":
        s["awaiting_daily_date"] = True
        s.pop("awaiting_daily_range", None)
        await _safe_edit(
            query,
            "🔍<b>Search by Date</b>\n\nSend the date in either format:\n\n"
            "📌<code>YYYY-MM-DD</code>\nExample: <code>2026-03-12</code>\n\n"
            "📌<code>DD-MM-YYYY</code>\nExample: <code>12-03-2026</code>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌Cancel",
                                      callback_data="ds_menu")],
            ]),
        )
    elif data == "ds_range":
        s["awaiting_daily_range"] = True
        s.pop("awaiting_daily_date", None)
        await _safe_edit(
            query,
            "📆<b>Search Date Range</b>\n\n"
            "Send the date range like this:\n\n"
            "📌<code>DD-MM-YYYY to DD-MM-YYYY</code>\n"
            "Example: <code>10-03-2026 to 12-03-2026</code>\n\n"
            "or\n\n"
            "📌<code>YYYY-MM-DD to YYYY-MM-DD</code>\n"
            "Example: <code>2026-03-10 to 2026-03-12</code>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌Cancel",
                                      callback_data="ds_menu")],
            ]),
        )
    elif data == "noop":
        return


# ────────────────────────────────────────────────────────────────────
# Callback helpers
# ────────────────────────────────────────────────────────────────────
async def _safe_edit(query: CallbackQuery, text: str,
                     *, reply_markup: InlineKeyboardMarkup | None = None
                     ) -> None:
    try:
        await query.message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest:
        try:
            await query.message.answer(text, reply_markup=reply_markup)
        except Exception:                       # noqa: BLE001
            pass
    except Exception:                           # noqa: BLE001
        pass


async def _cb_take(query: CallbackQuery, u: dict, data: str) -> None:
    country = data.replace("take_", "", 1)
    info = db.COUNTRIES["countries"].get(country)
    if not info or not isinstance(info, dict):
        await _safe_edit(query, f"Country data invalid: {country}")
        return
    available = list(info.get("numbers", []))
    if not available:
        # No fresh numbers in this country.  If the user is *already*
        # holding a number from this same country, just show the
        # active-number panel instead of confusing them with an error.
        if (u.get("current_country") == country
                and (u.get("current_number") or u.get("current_numbers"))):
            panel = core.build_active_number_panel(
                country_key=country,
                info=info,
                number=u.get("current_number") or "",
                numbers_extra=u.get("current_numbers") or [],
            )
            await _safe_edit(
                query,
                panel,
                reply_markup=core.active_number_buttons(
                    OTP_VIEW_URL,
                    current_number=u.get("current_number"),
                    numbers=u.get("current_numbers") or [],
                    iso=info.get("iso"),
                ),
            )
            return
        # Otherwise drop the user back into the country picker so they
        # can pick a country that still has stock.
        text_p, kb_p = _build_country_picker(
            "📞 <b>Choose a country to get a number:</b>"
        )
        if kb_p is None:
            await _safe_edit(query, "📦 No numbers available right now.")
        else:
            await _safe_edit(
                query,
                f"⚠️ <b>{info.get('display_name', country)}</b> "
                "is out of stock.\n\nPick another country:",
                reply_markup=kb_p,
            )
        return
    old_num = u.get("current_number")
    old_country = u.get("current_country")
    if old_num and old_country and old_country in db.COUNTRIES["countries"]:
        old_nums = u.get("current_numbers", [old_num]) or [old_num]
        # Release any currently-held numbers back into the country pool
        # in PostgreSQL (available=TRUE, assigned_to=NULL, assigned_at=NULL).
        await db.release_numbers(old_country, old_nums)

    limit = info.get("user_limit", DEFAULT_NUMBER_COUNT)
    # Atomic claim — `SELECT … FOR UPDATE SKIP LOCKED` prevents any
    # two concurrent users from receiving the same phone number.
    assigned: list[str] = await db.assign_numbers(
        country, query.from_user.id, limit)
    u["current_number"]  = assigned[0] if assigned else None
    u["current_numbers"] = assigned
    u["current_country"] = country
    u["awaiting_otp"]    = True
    u.setdefault("numbers_taken", []).extend(assigned)
    db.save_user(str(query.from_user.id))

    panel = core.build_active_number_panel(
        country_key=country,
        info=info,
        number=assigned[0] if assigned else "",
        numbers_extra=assigned,
    )
    await _safe_edit(
        query,
        panel,
        reply_markup=core.active_number_buttons(
            OTP_VIEW_URL,
            current_number=assigned[0] if assigned else None,
            numbers=assigned,
            iso=info.get("iso"),
        ),
    )
    log_message(f"User {query.from_user.id} took {assigned} from {country}")


async def _cb_user_change_number(query: CallbackQuery, u: dict) -> None:
    country = u.get("current_country")
    if not country:
        await _safe_edit(query, "No current number.")
        return
    info = db.COUNTRIES["countries"].get(country)
    if not info:
        await _safe_edit(query, f"{country} unavailable.")
        return
    old_nums = list(u.get("current_numbers") or [])
    old_primary = u.get("current_number")
    if old_primary and old_primary not in old_nums:
        old_nums = [old_primary] + old_nums
    if old_nums:
        await db.release_numbers(country, old_nums)
    limit = info.get("user_limit", DEFAULT_NUMBER_COUNT)
    assigned: list[str] = await db.assign_numbers(
        country, query.from_user.id, limit)
    if not assigned:
        await _safe_edit(query, f"No numbers left in {country}")
        return
    u["current_number"]  = assigned[0] if assigned else None
    u["current_numbers"] = assigned
    u["awaiting_otp"]    = True
    u.setdefault("numbers_taken", []).extend(assigned)
    db.save_user(str(query.from_user.id))
    panel = core.build_active_number_panel(
        country_key=country,
        info=info,
        number=assigned[0] if assigned else "",
        numbers_extra=assigned,
    )
    await _safe_edit(
        query,
        panel,
        reply_markup=core.active_number_buttons(
            OTP_VIEW_URL,
            current_number=assigned[0] if assigned else None,
            numbers=assigned,
            iso=info.get("iso"),
        ),
    )
    log_message(f"User {query.from_user.id} changed to {assigned}")


async def _cb_user_cancel_number(query: CallbackQuery, u: dict) -> None:
    """Return the user's currently-claimed numbers to the country
    pool and reset their state — same as Clear Prefix but inline.
    """
    old_country = u.get("current_country")
    old_nums = list(u.get("current_numbers") or [])
    if not old_nums and u.get("current_number"):
        old_nums = [u["current_number"]]
    if old_country and old_country in db.COUNTRIES["countries"] and old_nums:
        await db.release_numbers(old_country, old_nums)
    u["current_number"]  = None
    u["current_numbers"] = []
    u["current_country"] = None
    u["awaiting_otp"]    = False
    db.save_user(str(query.from_user.id))
    await _safe_edit(query, "🧹 Number cancelled.")
    log_message(f"User {query.from_user.id} cancelled active number")


async def _cb_user_change_country(query: CallbackQuery) -> None:
    text, kb = _build_country_picker(
        "🌍 <b>Pick a different country:</b>")
    if kb is None:
        await _safe_edit(query, "📦 No numbers available right now.")
        return
    await _safe_edit(query, text, reply_markup=kb)


async def _cb_payout_confirm(query: CallbackQuery, s: dict,
                             user_id: str, username: str | None,
                             bot: Bot) -> None:
    amount = s.get("payout_amount")
    method = s.get("payout_method")
    details = s.get("payout_details")
    if not amount or not method or not details:
        await _safe_edit(query,
                         "❌Payout data missing. Please start again.")
        return
    p = {
        "id":      str(int(time.time() * 1000)),
        "user":    user_id,
        "amount":  amount,
        "method":  method,
        "details": details,
        "status":  "pending",
    }
    db.PAYOUTS.append(p)
    db.save_payout(p)
    await _safe_edit(query, "Payout request sent!")
    btns = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Done",
                             callback_data=f"payout_done_{p['id']}"),
        InlineKeyboardButton(text="Decline",
                             callback_data=f"payout_decline_{p['id']}"),
    ]])
    for admin_id in [OWNER_ID, *db.ADMIN_IDS]:
        try:
            await bot.send_message(
                chat_id=admin_id,
                text=(
                    f"Payout Request\n"
                    f"User: <code>{user_id}</code> (@{username or 'N/A'})\n"
                    f"Amount: {p['amount']} rs\n"
                    f"Method: {p['method']}\n"
                    f"Details: <code>{p['details']}</code>"
                ),
                reply_markup=btns,
            )
        except Exception:                       # noqa: BLE001
            pass


async def _cb_fj_check(query: CallbackQuery, bot: Bot) -> None:
    if is_admin(query.from_user.id):
        await query.answer("You have admin access.")
        return
    all_joined, _ = await check_force_join(query.from_user.id, bot)
    if all_joined:
        await _safe_edit(
            query,
            "✅<b>Verification Successful!</b>\n\nYou may now use the bot.",
        )
        await query.message.answer(
            "Use the buttons below.",
            reply_markup=core.user_keyboard(),
        )
    else:
        await query.answer(
            "❌You haven't joined all required groups yet.",
            show_alert=True,
        )


async def _cb_fj_set_links(query: CallbackQuery, s: dict) -> None:
    if not is_owner(query.from_user.id):
        await query.answer("❌Owner-only.", show_alert=True)
        return
    s["awaiting_fj_links"] = True
    await _safe_edit(
        query,
        "🔗<b>Set Force Join Links</b>\n\n"
        "Send links/usernames/IDs (one per line). "
        "Public usernames, t.me/+invite links, and -100… IDs are all "
        "supported.",
    )


async def _cb_fj_skip_names(query: CallbackQuery, s: dict) -> None:
    if not is_owner(query.from_user.id):
        await query.answer("❌Owner-only.", show_alert=True)
        return
    s["awaiting_fj_names"] = False
    count = s.pop("fj_pending_names_count", 0)
    chats = db.FORCE_JOIN.get("chats", [])
    start_idx = len(chats) - count
    for i in range(count):
        idx = start_idx + i
        if idx < len(chats) and not chats[idx].get("button_name"):
            chats[idx]["button_name"] = f"Join Group {idx + 1}"
    db.save_force_join()
    panel_text, panel_kb = core.fj_owner_panel_text(db.FORCE_JOIN)
    await _safe_edit(
        query,
        f"✅Default button names assigned.\n\n"
        f"Total chats configured: <b>{len(chats)}</b>\n\n" + panel_text,
        reply_markup=panel_kb,
    )


async def _cb_fj_skip_private(query: CallbackQuery, s: dict) -> None:
    if not is_owner(query.from_user.id):
        await query.answer("❌Owner-only.", show_alert=True)
        return
    s["awaiting_fj_private_id"] = False
    idx = s.get("fj_current_private_idx", 0)
    queue = s.get("fj_private_queue", [])
    skipped_link = queue[idx]["link"] if idx < len(queue) else "unknown"
    await _safe_edit(
        query,
        f"⏭ Skipped private group:\n<code>{skipped_link}</code>\n\n"
        f"<i>This group was NOT added (no chat_id provided).</i>",
    )
    await _fj_process_next_private(query.message, s, idx + 1)


async def _cb_fj_cancel_links(query: CallbackQuery, s: dict) -> None:
    if not is_owner(query.from_user.id):
        await query.answer("❌Owner-only.", show_alert=True)
        return
    for k in ("awaiting_fj_links", "awaiting_fj_private_id",
              "awaiting_fj_names", "fj_private_queue",
              "fj_current_private_idx", "fj_pending_names_count",
              "fj_added_count"):
        s.pop(k, None)
    panel_text, panel_kb = core.fj_owner_panel_text(db.FORCE_JOIN)
    await _safe_edit(query, "❌Cancelled.\n\n" + panel_text,
                     reply_markup=panel_kb)


async def _cb_fj_toggle(query: CallbackQuery) -> None:
    if not is_owner(query.from_user.id):
        await query.answer("❌Owner-only.", show_alert=True)
        return
    if not db.FORCE_JOIN.get("chats"):
        await query.answer("⚠ Configure chats first using Set Links.",
                           show_alert=True)
        return
    db.FORCE_JOIN["enabled"] = not db.FORCE_JOIN.get("enabled", False)
    db.save_force_join()
    panel_text, panel_kb = core.fj_owner_panel_text(db.FORCE_JOIN)
    status_msg = ("✅Force Join Enabled!" if db.FORCE_JOIN["enabled"]
                  else "❌Force Join Disabled.")
    await _safe_edit(
        query,
        panel_text + f"\n<b>{status_msg}</b>",
        reply_markup=panel_kb,
    )


async def _cb_fj_view_groups(query: CallbackQuery) -> None:
    if not is_owner(query.from_user.id):
        await query.answer("❌Owner-only.", show_alert=True)
        return
    chats = db.FORCE_JOIN.get("chats", [])
    if not chats:
        await query.answer("No chats configured yet.", show_alert=True)
        return
    lines: list[str] = []
    for i, entry in enumerate(chats):
        cid = entry.get("chat_id", "?")
        title = entry.get("title", "Unknown")
        btn_name = entry.get("button_name", "—")
        link = entry.get("link", "—")
        invite_note = " ⚠ <i>invite-only</i>" if entry.get("invite_only") else ""
        lines.append(
            f"<b>{i+1}.</b> {title}{invite_note}\n"
            f"   🔘Button: <b>{btn_name}</b>\n"
            f"   🆔<code>{cid}</code>\n"
            f"   🔗{link}"
        )
    await _safe_edit(
        query,
        "📋<b>Force Join Chats</b>\n\n" + "\n\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙Back",
                                  callback_data="fj_back_panel")],
        ]),
    )


async def _cb_fj_remove_menu(query: CallbackQuery) -> None:
    if not is_owner(query.from_user.id):
        await query.answer("❌Owner-only.", show_alert=True)
        return
    chats = db.FORCE_JOIN.get("chats", [])
    if not chats:
        await query.answer("No chats to remove.", show_alert=True)
        return
    buttons = [
        [InlineKeyboardButton(text=f"🗑 {entry.get('title', f'Group {i+1}')}",
                              callback_data=f"fj_rem_{i}")]
        for i, entry in enumerate(chats)
    ]
    buttons.append([InlineKeyboardButton(text="🔙Back",
                                         callback_data="fj_back_panel")])
    await _safe_edit(
        query,
        "🗑 <b>Remove a Force Join Chat</b>\n\nSelect the chat to remove:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


async def _cb_fj_rem(query: CallbackQuery, data: str) -> None:
    if not is_owner(query.from_user.id):
        await query.answer("❌Owner-only.", show_alert=True)
        return
    try:
        idx = int(data.split("_")[-1])
    except ValueError:
        await query.answer("Invalid index.", show_alert=True)
        return
    chats = db.FORCE_JOIN.get("chats", [])
    if idx < 0 or idx >= len(chats):
        await query.answer("Chat not found.", show_alert=True)
        return
    entry = chats[idx]
    title = entry.get("title", f"Group {idx+1}")
    cid = entry.get("chat_id", "?")
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅Yes, Remove",
                              callback_data=f"fj_confirm_rem_{idx}"),
         InlineKeyboardButton(text="❌Cancel",
                              callback_data="fj_remove_menu")],
    ])
    await _safe_edit(
        query,
        f"⚠ <b>Confirm Removal</b>\n\n"
        f"Remove <b>{title}</b> (<code>{cid}</code>) from Force Join?\n\n"
        f"This will no longer require users to join this chat.",
        reply_markup=keyboard,
    )


async def _cb_fj_confirm_rem(query: CallbackQuery, data: str) -> None:
    if not is_owner(query.from_user.id):
        await query.answer("❌Owner-only.", show_alert=True)
        return
    try:
        idx = int(data.split("_")[-1])
    except ValueError:
        await query.answer("Invalid index.", show_alert=True)
        return
    chats = db.FORCE_JOIN.get("chats", [])
    if idx < 0 or idx >= len(chats):
        await query.answer("Chat not found.", show_alert=True)
        return
    removed = chats.pop(idx)
    db.FORCE_JOIN["chats"] = chats
    if not chats:
        db.FORCE_JOIN["enabled"] = False
    db.save_force_join()
    panel_text, panel_kb = core.fj_owner_panel_text(db.FORCE_JOIN)
    await _safe_edit(
        query,
        f"✅<b>{removed.get('title', 'Unknown')}</b> removed.\n\n" + panel_text,
        reply_markup=panel_kb,
    )


async def _cb_fj_scan(query: CallbackQuery) -> None:
    if not is_owner(query.from_user.id):
        await query.answer("❌Owner-only.", show_alert=True)
        return

    for entry in db.FORCE_JOIN.get("chats", []):
        cid = entry.get("chat_id")
        if cid and str(cid) in db.BOT_KNOWN_CHATS:
            entry["title"] = db.BOT_KNOWN_CHATS[str(cid)].get(
                "title", entry.get("title"))
            entry.pop("invite_only", None)
    db.save_force_join()

    if not db.BOT_KNOWN_CHATS:
        await _safe_edit(
            query,
            "📡<b>Scan Bot's Groups</b>\n\n"
            "⚠ No groups detected yet.\n\n"
            "Add the bot to your groups/channels first.\n"
            "Once added, this list updates automatically.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙Back",
                                      callback_data="fj_back_panel")],
            ]),
        )
        return

    configured_ids = {c.get("chat_id") for c in db.FORCE_JOIN.get("chats", [])}
    buttons: list[list[InlineKeyboardButton]] = []
    already_added: list[str] = []
    for cid_str, info in db.BOT_KNOWN_CHATS.items():
        cid = info.get("chat_id", int(cid_str))
        title = info.get("title", cid_str)
        chat_type = info.get("type", "")
        type_icon = "📢" if chat_type == "channel" else "👥"
        if cid in configured_ids:
            already_added.append(f"{type_icon} {title}")
        else:
            buttons.append([InlineKeyboardButton(
                text=f"➕{type_icon} {title}",
                callback_data=f"fj_add_known_{cid_str}")])

    text_scan = ("📡<b>Scan Bot's Groups</b>\n\n"
                 "Select a group/channel to add to Force Join:\n")
    if already_added:
        text_scan += "\n<b>Already configured:</b>\n"
        text_scan += "\n".join(f"✅{t}" for t in already_added) + "\n"
    if not buttons and not already_added:
        text_scan += "\nNo groups found."
    buttons.append([InlineKeyboardButton(text="🔙Back",
                                         callback_data="fj_back_panel")])
    await _safe_edit(
        query, text_scan,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


async def _cb_fj_add_known(query: CallbackQuery, data: str) -> None:
    if not is_owner(query.from_user.id):
        await query.answer("❌Owner-only.", show_alert=True)
        return
    cid_str = data.replace("fj_add_known_", "")
    known = db.BOT_KNOWN_CHATS.get(cid_str)
    if not known:
        await query.answer("Chat no longer found in registry.",
                           show_alert=True)
        return
    cid = known.get("chat_id", int(cid_str))
    title = known.get("title", cid_str)
    chat_type = known.get("type", "")
    configured_ids = {c.get("chat_id") for c in db.FORCE_JOIN.get("chats", [])}
    if cid in configured_ids:
        await query.answer(f"'{title}' is already in the list.",
                           show_alert=True)
        return
    join_link = (core.chat_id_to_tme(cid)
                 if chat_type in ("supergroup", "channel") else "")
    new_idx = len(db.FORCE_JOIN.get("chats", []))
    db.FORCE_JOIN.setdefault("chats", []).append({
        "chat_id":     cid,
        "title":       title,
        "link":        join_link,
        "button_name": f"Join Group {new_idx + 1}",
    })
    db.save_force_join()
    await query.answer(f"✅{title} added!")
    await _cb_fj_scan(query)


async def _cb_del_country(query: CallbackQuery, data: str) -> None:
    if not is_admin(query.from_user.id):
        await query.answer("❌Admin only.", show_alert=True)
        return
    c = data.replace("del_", "", 1)
    if c not in db.COUNTRIES["countries"]:
        await query.answer("Country not found.", show_alert=True)
        return
    info = db.COUNTRIES["countries"][c]
    flag = info.get("flag", "")
    display = info.get("display_name", c.upper())
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅Yes, Delete",
                              callback_data=f"confirm_delete_country_{c}"),
         InlineKeyboardButton(text="❌Cancel",
                              callback_data="cancel_delete_country")],
    ])
    await _safe_edit(
        query,
        f"⚠ Delete <b>{flag} {display}</b>?",
        reply_markup=keyboard,
    )


async def _cb_confirm_delete_country(query: CallbackQuery, data: str) -> None:
    if not is_admin(query.from_user.id):
        await query.answer("❌Admin only.", show_alert=True)
        return
    c = data.replace("confirm_delete_country_", "", 1)
    if c in db.COUNTRIES["countries"]:
        db.delete_country(c)
        await _safe_edit(query, f"✅Deleted {c}.")
        log_message(f"Admin deleted country {c}")
    else:
        await _safe_edit(query, "❌Country not found.")


async def _cb_manage_country(query: CallbackQuery, s: dict,
                             data: str) -> None:
    if not is_admin(query.from_user.id):
        await query.answer("❌Admin only.", show_alert=True)
        return
    c = data.replace("manage_", "", 1)
    info = db.COUNTRIES["countries"].get(c)
    if not info:
        await query.answer("Country not found.", show_alert=True)
        return
    s["manage_country"] = c
    await _safe_edit(
        query,
        f"<b>Managing: {info.get('flag', '')} {info.get('display_name', c)} "
        f"({info.get('dial_code', '')})</b>\n\n"
        f"📦Numbers: <b>{len(info.get('numbers', []))}</b>\n"
        f"💰Price: <b>{info.get('price', DEFAULT_PRICE)} rs</b>\n"
        f"👥Per User Limit: <b>{info.get('user_limit', DEFAULT_NUMBER_COUNT)}</b>\n"
        f"📊Total OTPs: <b>{info.get('total_otps', 0)}</b>",
        reply_markup=core.manage_country_kb(),
    )


async def _commit_uploaded_numbers(message_or_query, s: dict) -> bool:
    """Drain the upload buffer into the country, save, and reply with
    the premium "Numbers Added Successfully" card (with a
    📢 Broadcast button).  Returns True on success.

    Accepts either a `Message` (text-paste flow) or a `CallbackQuery`
    (DONE UPLOAD button flow) — picks the right reply method
    accordingly.
    """
    c = s.get("manage_country")
    buf = s.pop("upload_buffer", []) or []
    s.pop("awaiting_file", None)
    s.pop("upload_file_count", None)

    is_query = hasattr(message_or_query, "data")  # CallbackQuery has .data

    async def _reply(text: str, **kwargs):
        if is_query:
            await _safe_edit(message_or_query, text, **kwargs)
        else:
            await message_or_query.answer(text, **kwargs)

    if not c or c not in db.COUNTRIES["countries"]:
        await _reply("❌ No country selected.")
        return False
    if not buf:
        await _reply(
            "ℹ Nothing to upload yet — paste numbers (one per line) "
            "or send a <code>.txt</code> file first."
        )
        return False
    inserted = await db.add_numbers(c, buf)
    log_message(f"Admin uploaded {inserted} new numbers to {c} "
                f"(skipped {len(buf) - inserted} duplicates)")

    info = db.COUNTRIES["countries"][c]
    card = core.build_numbers_added_text(
        country_display=info.get("display_name") or c,
        iso=info.get("iso"),
        service=info.get("service"),
        quantity=inserted,
    )
    # Per spec: NO automatic "Broadcast this" prompt after a country
    # add / numbers upload — the admin uses the standalone Broadcast
    # menu when they actually want to announce something.
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Back",
                              callback_data="manage_back",
                              style="primary")],
    ])
    await _reply(card, reply_markup=kb)
    return True


async def _cb_upload_done(query: CallbackQuery, s: dict) -> None:
    await _commit_uploaded_numbers(query, s)


async def _cb_clear_numbers(query: CallbackQuery, s: dict) -> None:
    c = s.get("manage_country")
    if not c or c not in db.COUNTRIES["countries"]:
        await _safe_edit(query, "❌No country selected.")
        return
    info = db.COUNTRIES["countries"][c]
    cnt = len(info.get("numbers", []))
    flag = info.get("flag", core.GLOBE)
    display = info.get("display_name", c.upper())
    dial = info.get("dial_code", "")
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅Yes, Clear All",
                              callback_data="confirm_clear_numbers")],
        [InlineKeyboardButton(text="❌Cancel",
                              callback_data="cancel_clear_numbers")],
    ])
    await _safe_edit(
        query,
        f"⚠ <b>WARNING</b>\n\n"
        f"You are about to delete ALL numbers from:\n\n"
        f"{flag} <b>{display}</b> ({dial})\n\n"
        f"📦Total Numbers: <b>{cnt}</b>\n\n"
        f"Are you sure?",
        reply_markup=keyboard,
    )


async def _cb_confirm_clear_numbers(query: CallbackQuery, s: dict) -> None:
    c = s.get("manage_country")
    if not c or c not in db.COUNTRIES["countries"]:
        await _safe_edit(query, "❌No country selected.")
        return
    cleared = await db.clear_numbers_for_country(c)
    display = db.COUNTRIES["countries"][c].get("display_name", c.upper())
    await _safe_edit(
        query,
        f"✅ Cleared <b>{cleared}</b> numbers from <b>{display}</b>",
    )
    log_message(f"Admin cleared {cleared} numbers from {c}")


async def _cb_cancel_clear_numbers(query: CallbackQuery, s: dict) -> None:
    c = s.get("manage_country")
    if c and c in db.COUNTRIES["countries"]:
        info = db.COUNTRIES["countries"][c]
        await _safe_edit(
            query,
            f"<b>Managing: {info.get('flag', '')} {info.get('display_name', c)} "
            f"({info.get('dial_code', '')})</b>\n\n"
            f"📦Numbers: <b>{len(info.get('numbers', []))}</b>\n"
            f"💰Price: <b>{info.get('price', DEFAULT_PRICE)} rs</b>\n"
            f"👥Per User Limit: <b>{info.get('user_limit', DEFAULT_NUMBER_COUNT)}</b>\n"
            f"📊Total OTPs: <b>{info.get('total_otps', 0)}</b>",
            reply_markup=core.manage_country_kb(),
        )
    else:
        await _safe_edit(query, "❌Cancelled. No country selected.")


async def _cb_manage_back(query: CallbackQuery, s: dict) -> None:
    """Return to the country-manage panel after the upload-success card."""
    c = s.get("manage_country")
    if not c or c not in db.COUNTRIES["countries"]:
        await _safe_edit(query, "Use the menu to pick a country.")
        return
    info = db.COUNTRIES["countries"][c]
    flag = info.get("flag") or core.GLOBE
    service = info.get("service") or ""
    service_label = f" {service}" if service else ""
    header = f"{flag} <b>{info.get('display_name') or c}</b>" \
             f"{service_label} ({info.get('dial_code') or ''})"
    await _safe_edit(
        query,
        f"<b>Managing: {header}</b>\n\n"
        f"📦Numbers: <b>{len(info.get('numbers', []))}</b>\n"
        f"💰Price: <b>{info.get('price', DEFAULT_PRICE)} rs</b>\n"
        f"👥Per User Limit: <b>{info.get('user_limit', DEFAULT_NUMBER_COUNT)}</b>\n"
        f"📊Total OTPs: <b>{info.get('total_otps', 0)}</b>",
        reply_markup=core.manage_country_kb(),
    )


async def _cb_broadcast_confirm(query: CallbackQuery, s: dict,
                                bot: Bot) -> None:
    msg = s.pop("broadcast_msg", None)
    s.pop("broadcast_user_ids", None)         # legacy slot, no longer used
    if not msg:
        await _safe_edit(query, "❌Broadcast data lost. Please try again.")
        return
    progress_msg = await query.message.edit_text(
        "<b>🚀 Broadcast starting…</b>\n\n"
        "Streaming users from PostgreSQL…",
    )
    # Run as a top-level task so the bot stays fully responsive
    # (incoming OTPs / callbacks / messages keep working) while the
    # broadcast streams users from the DB.
    safe_task(
        core.run_broadcast(
            bot,
            progress_msg=progress_msg,
            text=msg,
            user_ids=None,                    # stream every user from PG
            concurrency=BROADCAST_CONCURRENCY,
            progress_every=BROADCAST_PROGRESS_EVERY,
            sender_admin=int(query.from_user.id) if query and query.from_user else None,
        ),
        name="broadcast-admin",
    )


async def _cb_set_user_limit(query: CallbackQuery, s: dict) -> None:
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📌This Country",
                              callback_data="set_limit_this_country"),
         InlineKeyboardButton(text="🌍All Countries",
                              callback_data="set_limit_all_countries")],
        [InlineKeyboardButton(text="🔙Back", callback_data="back_admin")],
    ])
    await _safe_edit(query, "👥Apply user limit to:",
                     reply_markup=keyboard)


async def _cb_country_performance(query: CallbackQuery, s: dict) -> None:
    c = s.get("manage_country")
    if not c or c not in db.COUNTRIES["countries"]:
        await _safe_edit(query, "❌No country selected.")
        return
    info = db.COUNTRIES["countries"][c]
    txt = (
        f"📊<b>Country Performance — {info.get('flag', '')} "
        f"{info.get('display_name', c)}</b>\n\n"
        f"📦Active Numbers: <b>{len(info.get('numbers', []))}</b>\n"
        f"📊Total OTPs: <b>{info.get('total_otps', 0)}</b>\n"
        f"💵Total Earnings: <b>{round(info.get('total_earnings', 0.0), 2)} rs</b>\n"
        f"💰Price: <b>{info.get('price', DEFAULT_PRICE)} rs</b>\n"
        f"👥Per-user Limit: <b>{info.get('user_limit', DEFAULT_NUMBER_COUNT)}</b>"
    )
    await _safe_edit(
        query, txt,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙Back", callback_data="back_admin")],
        ]),
    )


async def _cb_detailed_country_stats(query: CallbackQuery) -> None:
    if not db.COUNTRIES["countries"]:
        await _safe_edit(query, "No countries yet.")
        return
    lines = ["<b>📊Detailed Country Stats</b>\n"]
    for c, info in db.COUNTRIES["countries"].items():
        flag = info.get("flag", "")
        display = info.get("display_name", c.upper())
        dial = info.get("dial_code", "")
        lines.append(
            f"\n{flag} <b>{display}</b> ({dial})\n"
            f"  📦{len(info.get('numbers', []))} active "
            f"| 📊{info.get('total_otps', 0)} OTPs "
            f"| 💵{round(info.get('total_earnings', 0.0), 2)} rs"
        )
    await _safe_edit(
        query, "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙Back", callback_data="back_admin")],
        ]),
    )


async def _cb_admin_remove(query: CallbackQuery, data: str) -> None:
    if not is_owner(query.from_user.id):
        await query.answer("❌Owner-only.", show_alert=True)
        return
    try:
        aid = int(data.replace("admin_remove_", ""))
    except ValueError:
        return
    if aid in db.ADMIN_IDS:
        db.ADMIN_IDS.remove(aid)
        db.save_admins()
        await _safe_edit(query, f"✅Admin <code>{aid}</code> removed.")
        log_message(f"Owner removed admin {aid}")
    else:
        await query.answer("Not an admin.", show_alert=True)


async def _cb_payout_done(query: CallbackQuery, data: str, bot: Bot) -> None:
    if not is_admin(query.from_user.id):
        await query.answer("❌Admin only.", show_alert=True)
        return
    pid = data.replace("payout_done_", "", 1)
    p = next((x for x in db.PAYOUTS if str(x.get("id")) == pid), None)
    if not p:
        await query.answer("Payout not found.", show_alert=True)
        return
    if p.get("status") != "pending":
        await query.answer("Already processed.", show_alert=True)
        return
    p["status"] = "done"
    db.save_payout(p)
    user_id = str(p.get("user", ""))
    u = db.USERS.get(user_id)
    if u:
        u["balance"] = max(0.0, float(u.get("balance", 0)) - float(p.get("amount", 0)))
        db.save_user(user_id)
        try:
            await bot.send_message(
                chat_id=int(user_id),
                text=(f"✅Payout of <b>{p.get('amount')} rs</b> "
                      f"completed via {p.get('method')}."),
            )
        except Exception:                       # noqa: BLE001
            pass
    await _safe_edit(query,
                     f"✅Payout <code>{pid}</code> marked as done.")
    log_message(f"Payout {pid} marked done by admin")


async def _cb_payout_decline(query: CallbackQuery, data: str,
                             bot: Bot) -> None:
    if not is_admin(query.from_user.id):
        await query.answer("❌Admin only.", show_alert=True)
        return
    pid = data.replace("payout_decline_", "", 1)
    p = next((x for x in db.PAYOUTS if str(x.get("id")) == pid), None)
    if not p:
        await query.answer("Payout not found.", show_alert=True)
        return
    if p.get("status") != "pending":
        await query.answer("Already processed.", show_alert=True)
        return
    p["status"] = "declined"
    db.save_payout(p)
    user_id = str(p.get("user", ""))
    try:
        await bot.send_message(
            chat_id=int(user_id),
            text=f"❌Your payout request <code>{pid}</code> was declined.",
        )
    except Exception:                           # noqa: BLE001
        pass
    await _safe_edit(query,
                     f"❌Payout <code>{pid}</code> declined.")
    log_message(f"Payout {pid} declined")


async def _cb_ds_menu(query: CallbackQuery) -> None:
    core.ensure_today()
    today_str = core._today_str()
    today_otps = db.DAILY_STATS.get("today", {}).get("total_otps", 0)
    today_earnings = round(
        float(db.DAILY_STATS.get("today", {}).get("total_earnings", 0)), 2)
    history_days = len(db.DAILY_STATS.get("history", {}))
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅Today", callback_data="ds_today"),
         InlineKeyboardButton(text="📅Yesterday",
                              callback_data="ds_yesterday")],
        [InlineKeyboardButton(text="🔍Search by Date",
                              callback_data="ds_search")],
        [InlineKeyboardButton(text="📆Date Range",
                              callback_data="ds_range")],
        [InlineKeyboardButton(text="🔙Back", callback_data="back_admin")],
    ])
    await _safe_edit(
        query,
        f"📊<b>Daily Statistics</b>\n\n"
        f"📅Today (<code>{today_str}</code>):\n"
        f"  📦OTPs: <b>{today_otps}</b>  |  "
        f"💰Earnings: <b>{today_earnings} rs</b>\n\n"
        f"📂Stored history: <b>{history_days}</b> day(s)\n\n"
        f"Choose an option:",
        reply_markup=keyboard,
    )


async def _cb_ds_today(query: CallbackQuery) -> None:
    core.ensure_today()
    today_str = core._today_str()
    day_data = db.DAILY_STATS.get("today", {})
    await _safe_edit(
        query,
        core.format_daily_stats(today_str, day_data),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙Back", callback_data="ds_menu")],
        ]),
    )


async def _cb_ds_yesterday(query: CallbackQuery) -> None:
    core.ensure_today()
    yesterday_d = (datetime.date.fromisoformat(core._today_str())
                   - datetime.timedelta(days=1))
    yesterday_str = yesterday_d.strftime("%Y-%m-%d")
    hist = db.DAILY_STATS.get("history", {}).get(yesterday_str)
    back_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙Back", callback_data="ds_menu")],
    ])
    if not hist:
        await _safe_edit(
            query,
            f"📭No data for yesterday (<b>{yesterday_str}</b>).",
            reply_markup=back_kb,
        )
        return
    await _safe_edit(
        query,
        core.format_daily_stats(yesterday_str, hist),
        reply_markup=back_kb,
    )


# ────────────────────────────────────────────────────────────────────
# Force-join input resolution (public link / username / chat_id /
# private invite link).  Mirrors `_fj_resolve_input` from main122.py.
# ────────────────────────────────────────────────────────────────────
async def _resolve_fj_input(raw: str, bot: Bot) -> dict | None:
    raw = raw.strip().rstrip("/")

    if re.match(r"^(?:https?://)?t\.me/\+", raw) or "joinchat" in raw:
        invite_url = raw if raw.startswith("http") else "https://" + raw
        return {"_private_invite": True, "link": invite_url}

    if re.match(r"^-\d{5,}$", raw):
        cid = int(raw)
        return {"chat_id": cid, "title": f"Group {raw}",
                "link": core.chat_id_to_tme(cid)}
    if re.match(r"^\+\d{5,}$", raw):
        cid = -int(raw[1:])
        return {"chat_id": cid, "title": f"Group {raw}",
                "link": core.chat_id_to_tme(cid)}

    if re.match(r"^@[a-zA-Z][a-zA-Z0-9_]{3,}$", raw):
        chat_ref: str | int = raw
    elif re.match(r"^[a-zA-Z][a-zA-Z0-9_]{3,}$", raw):
        chat_ref = "@" + raw
    elif "t.me/" in raw:
        m = re.search(r"t\.me/([a-zA-Z][a-zA-Z0-9_]{3,})$", raw)
        if not m:
            return None
        chat_ref = "@" + m.group(1)
    else:
        return None

    try:
        chat = await bot.get_chat(chat_ref)
    except Exception as e:                      # noqa: BLE001
        raise RuntimeError(f"could not resolve {raw}: {e}") from e
    return {
        "chat_id": chat.id,
        "title":   chat.title or chat.full_name or chat_ref,
        "link":    f"https://t.me/{chat.username}" if chat.username else "",
    }


# ════════════════════════════════════════════════════════════════════
#                              main()
# ════════════════════════════════════════════════════════════════════
async def main() -> None:
    log.warning("Starting bot…")
    await db.init(
        DATABASE_URL,
        min_size=DB_POOL_MIN,
        max_size=DB_POOL_MAX,
        command_timeout=DB_COMMAND_TIMEOUT,
    )

    # ── Pyrogram (user-session group reader) — log in FIRST ────────
    # First-run login is interactive: Pyrogram sends an SMS code to
    # USER_PHONE and prompts on stdin (`Enter confirmation code:`).
    # We do this BEFORE start_polling so the prompt is visible.
    # After the first successful login, `user_session.session` is
    # written to disk and reused on subsequent runs without prompting.
    pyro_client = await _pyrogram_login()

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    # OTP worker pool — concurrent burst-safe processing.
    for i in range(OTP_WORKER_COUNT):
        safe_task(otp_worker(bot), name=f"otp-worker-{i}")

    # Warm RAM dedupe from PG (last hour) so restarts don't reprocess
    # messages that were already forwarded right before shutdown.
    await _warm_dedupe_from_pg()

    # Background tasks: daily reset + Pyrogram catch-up / keepalive +
    # processed_messages janitor.
    safe_task(core.daily_reset_loop(), name="daily-reset")
    safe_task(_processed_messages_janitor(),
              name="processed-messages-janitor")
    if pyro_client is not None:
        safe_task(_pyrogram_keepalive_loop(pyro_client),
                  name="pyrogram-keepalive-loop")

    log.warning("Bot ready: %d users / %d countries / %d admins",
                len(db.USERS), len(db.COUNTRIES["countries"]),
                len(db.ADMIN_IDS))

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()
        if pyro_client is not None:
            try:
                if pyro_client.is_connected:
                    await pyro_client.stop()
            except Exception:                       # noqa: BLE001
                pass
        await db.shutdown()


def _runtime_loop() -> None:
    """Process-level crash guard — never let the bot stay dead.

    On a crash we re-exec the entire Python process via ``os.execv``
    rather than calling ``asyncio.run`` a second time.  Re-running
    ``asyncio.run`` inside the same process creates a fresh event
    loop but keeps every module-level asyncio object bound to the
    *previous* loop, which Python 3.13+ rejects with
    ``RuntimeError: <…> is bound to a different event loop``.  A
    full re-exec sidesteps that entirely.
    """
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[Stopped] Bot stopped by user.")
        sys.exit(0)
    except Exception as e:                      # noqa: BLE001
        log.error("Bot crashed: %s — restarting in 5s", e, exc_info=True)
        log_message(f"Bot crashed: {e} — restarting in 5s")
        time.sleep(5)
        # Re-exec ourselves with a fresh interpreter.
        os.execv(sys.executable, [sys.executable, *sys.argv])


if __name__ == "__main__":
    _runtime_loop()
