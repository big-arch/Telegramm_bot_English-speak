"""Proving who is on the other end of a Mini App request.

A Mini App is an ordinary web page: its URL is guessable and anyone can POST to
the endpoints behind it. What makes it trustworthy is `initData` — a blob
Telegram hands the page, signed with a key derived from the bot token. Checking
that signature here is the only thing standing between "the learner saved a
word" and "anyone on the internet can write to any account".

The algorithm is Telegram's, and the two details that trip people up are both
load-bearing: the secret is `HMAC-SHA256("WebAppData", bot_token)` — note the
inverted argument order, the *constant* is the key — and the hash is computed
over the fields sorted by name with `hash` itself removed.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from urllib.parse import parse_qsl

logger = logging.getLogger(__name__)

# Telegram refreshes initData when the app reopens, so an old blob is either a
# very stale tab or a replay. A day is generous for the former.
MAX_AGE_SECONDS = 24 * 60 * 60


class InvalidInitData(ValueError):
    """The request did not come from Telegram, or is too old to trust."""


def parse(init_data: str, *, bot_token: str, max_age: int = MAX_AGE_SECONDS) -> dict:
    """Return the verified payload, or raise.

    Never trust a field from this string before this function has returned —
    `user.id` in particular decides whose vocabulary gets written to.
    """
    if not init_data:
        raise InvalidInitData("no initData")

    try:
        fields = dict(parse_qsl(init_data, strict_parsing=True))
    except ValueError as exc:
        raise InvalidInitData(f"malformed initData: {exc}") from exc

    received = fields.pop("hash", None)
    if not received:
        raise InvalidInitData("initData carries no hash")

    check_string = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    # The constant is the key and the token is the message — the inverse of
    # what the name suggests, and the usual reason a correct-looking
    # implementation rejects every request.
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected, received):
        raise InvalidInitData("signature mismatch")

    issued = int(fields.get("auth_date", 0) or 0)
    if max_age and (time.time() - issued) > max_age:
        raise InvalidInitData("initData has expired")

    try:
        fields["user"] = json.loads(fields.get("user", "{}"))
    except json.JSONDecodeError as exc:
        raise InvalidInitData(f"malformed user field: {exc}") from exc

    return fields


def telegram_id(init_data: str, *, bot_token: str) -> int:
    user = parse(init_data, bot_token=bot_token).get("user") or {}
    tg_id = user.get("id")
    if not isinstance(tg_id, int):
        raise InvalidInitData("initData carries no user id")
    return tg_id
