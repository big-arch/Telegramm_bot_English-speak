"""Which handler catches which kind of message.

This file exists because of one bug. Vision worked, the archives worked, the
prompt worked — and the bot still "could not see photos", because a picture
sent as a file carries no `photo` field and was landing in the wrong-media
handler, which answered "that's a file, not a voice message". Desktop Telegram
sends a dragged-in image that way by default, so this was not an edge case; it
was most of how the feature was being used.

Routing is therefore worth asserting directly. The handler bodies are replaced
with recorders: what is under test is which one wins, not what it does.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from aiogram import Bot, Dispatcher
from aiogram.types import (
    Audio,
    Chat,
    Document,
    Message,
    PhotoSize,
    Update,
    User as TgUser,
    Voice,
)

from bot.handlers import router as root_router


FIRED: list[str] = []


@pytest.fixture(scope="module")
def dispatcher() -> Dispatcher:
    """One dispatcher for the module: a router can only ever be attached once.

    The real callbacks are put back afterwards. `root_router` is module-level
    state shared with every other test in the run, and leaving it stubbed would
    make some later failure depend on test ordering — the worst kind to debug.
    """
    original = []
    for sub in root_router.sub_routers:
        for handler in sub.message.handlers:
            original.append((handler, handler.callback))

            def make(recorded: str):
                async def record(message, **kwargs):
                    FIRED.append(recorded)

                return record

            handler.callback = make(handler.callback.__name__)

    dp = Dispatcher()
    dp.include_router(root_router)
    yield dp

    for handler, callback in original:
        handler.callback = callback


def _message(**kwargs) -> Message:
    return Message(
        message_id=1,
        date=datetime.now(),
        chat=Chat(id=1, type="private"),
        from_user=TgUser(id=1, is_bot=False, first_name="T"),
        **kwargs,
    )


PHOTO = [PhotoSize(file_id="p", file_unique_id="p", width=10, height=10, file_size=900)]


def _document(mime: str | None) -> Document:
    return Document(file_id="d", file_unique_id="d", mime_type=mime, file_size=2000)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message, expected",
    [
        (_message(photo=PHOTO), "on_photo"),
        # The whole reason this file exists.
        (_message(document=_document("image/jpeg")), "on_image_document"),
        (_message(document=_document("image/png")), "on_image_document"),
        (_message(document=_document("image/heic")), "on_image_document"),
        # Everything else still goes where it went.
        (_message(document=_document("application/pdf")), "on_wrong_media"),
        (_message(document=_document(None)), "on_wrong_media"),
        (_message(audio=Audio(file_id="a", file_unique_id="a", duration=3)), "on_wrong_media"),
        (_message(voice=Voice(file_id="v", file_unique_id="v", duration=3)), "on_voice"),
        (_message(text="hello"), "on_text"),
    ],
)
async def test_each_kind_of_message_reaches_its_own_handler(dispatcher, message, expected):
    FIRED.clear()
    await dispatcher.feed_update(Bot(token="1:x"), Update(update_id=1, message=message))
    assert FIRED == [expected]
