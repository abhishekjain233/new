"""Regression tests for ``core.parse_otp``.

These cover both the simple ``+phone\\nOTP`` format that the bot has
always handled and the richer multi-line forwarded formats produced
by external OTP-forwarder bots (TempNum, CRAPI, etc.) — including
forwards that omit the ``+`` prefix, prefix every label with an
emoji, and use either hyphenated (``448-275``) or plain (``723154``)
OTP codes.

Run from the repo root::

    pytest tests/test_parse_otp.py -v
"""
from __future__ import annotations

import importlib.util
import os
import sys
import types

import pytest


def _load_core():
    """Import ``core.py`` from the repo root with the heavy aiogram /
    db / emojis dependencies stubbed out, so the parser can be tested
    in isolation."""
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.modules.setdefault("db", types.ModuleType("db"))
    emojis_mod = types.ModuleType("emojis")
    emojis_mod.country_emoji_html = lambda *a, **k: ""
    emojis_mod.service_emoji_id = lambda *a, **k: None
    emojis_mod.country_emoji_id = lambda *a, **k: None
    sys.modules.setdefault("emojis", emojis_mod)

    spec = importlib.util.spec_from_file_location(
        "core", os.path.join(repo_root, "core.py"),
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


core = _load_core()


# ────────────────────────────────────────────────────────────────────
# Happy path — every format the bot must understand
# ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "label,text,expected_number,expected_otp",
    [
        (
            "simple +phone newline otp (legacy format)",
            "+2290144790007\n198728",
            "+2290144790007",
            "198728",
        ),
        (
            "simple phone without + (forwards that strip the plus)",
            "2290144790007\n198728",
            "2290144790007",
            "198728",
        ),
        (
            "+phone OTP on a single line",
            "+2290144790007 198728 thanks",
            "+2290144790007",
            "198728",
        ),
        (
            "hyphenated 6-digit OTP",
            "+2290144790007\n448-275",
            "+2290144790007",
            "448275",
        ),
        (
            "TempNum-style multi-line forward with emoji labels",
            "🔥 Ethiopia WhatsApp OTP Recieved! ✨\n"
            "⏰ Time: 2026-05-19 16:48:21 IST\n"
            "🏞 Country: Ethiopia 🇪🇹\n"
            "📱 Service: WhatsApp\n"
            "☎ Number: +251975101413\n"
            "🔑 OTP: 448-275\n\n"
            "📥 Full Message:\n"
            "<#> Your WhatsApp code: 448-275nDon't share this code",
            "+251975101413",
            "448275",
        ),
        (
            "TempNum-style without + prefix on the phone line",
            "🔥 Cameroon WhatsApp OTP Recieved! ✨\n"
            "⏰ Time: 2026-05-19 16:48:21 IST\n"
            "🏞 Country: Cameroon\n"
            "📱 Service: WhatsApp\n"
            "☎ Number: 237651234567\n"
            "🔑 OTP: 884512",
            "237651234567",
            "884512",
        ),
        (
            "emoji-prefixed Number label with bare digits",
            "☎ Number: 251975101413\n🔑 OTP: 448275",
            "251975101413",
            "448275",
        ),
        (
            "long-body 'Forwarded from' footer is ignored",
            "🔥 Brazil WhatsApp OTP Recieved! ✨\n"
            "⏰ Time: 2026-05-19 16:48:21 IST\n"
            "🏞 Country: Brazil 🇧🇷\n"
            "📱 Service: WhatsApp\n"
            "☎ Number: +5511987654321\n"
            "🔑 OTP: 552031\n"
            "📥 Full Message:\n"
            "<#> Your WhatsApp code: 552031nDon't share this code\n\n"
            "ℹ Forwarded from CRAPI Xisora Poller",
            "+5511987654321",
            "552031",
        ),
    ],
)
def test_parse_otp_happy_paths(label, text, expected_number, expected_otp):
    number, otp_digits, _otp_pretty = core.parse_otp(text)
    assert otp_digits == expected_otp, f"OTP mismatch for {label!r}"
    assert number == expected_number, f"Number mismatch for {label!r}"


# ────────────────────────────────────────────────────────────────────
# Negative cases — make sure the parser still rejects ambiguous input
# ────────────────────────────────────────────────────────────────────

def test_parse_otp_returns_none_when_no_code_present():
    """A bare phone number with no code at all must not yield an OTP."""
    number, otp_digits, _ = core.parse_otp("+2290144790007 just a phone here")
    assert otp_digits is None
    assert number is None


def test_parse_otp_ignores_bare_year_lookalike():
    """``+phone\\n2026`` must not be parsed as a 4-digit OTP — ``2026``
    is almost always a year, not a code."""
    number, otp_digits, _ = core.parse_otp("+2290144790007\n2026")
    assert otp_digits is None
    assert number is None


def test_parse_otp_drops_otp_when_no_phone_in_text():
    """If only an OTP appears with no phone-shaped number, ``number``
    is None — downstream code logs and skips."""
    number, otp_digits, _ = core.parse_otp("Your code is 887095")
    assert otp_digits == "887095"
    assert number is None


def test_parse_otp_does_not_pick_up_timestamps_as_phone():
    """A timestamp like ``2026-05-09 18:27:09`` on a ``Time:`` line
    must never be treated as the phone number."""
    text = (
        "🔥 Egypt WhatsApp OTP Recieved! ✨\n"
        "⏰ Time: 2026-05-09 18:27:09 IST\n"
        "☎ Number: +201253754099\n"
        "🔑 OTP: 552031"
    )
    number, otp_digits, _ = core.parse_otp(text)
    assert number == "+201253754099"
    assert otp_digits == "552031"
