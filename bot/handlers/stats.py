"""How the product is actually doing, for whoever built it.

Deliberately aggregate. Nothing here shows a message, a transcript or a name —
the operator needs to know whether the thing works, not what anyone said to it,
and a learning product that starts reading its users' conversations to measure
itself has become a different kind of product.

The numbers are chosen against the obvious temptation. A total-users figure
only goes up and tells you nothing; what a new product needs to know is how
many of the people who arrived said a single word, and how many of those came
back on a second day. The funnel is the actionable one: a step that loses most
of the people who reached it is a bug with a location.
"""

from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.config import settings
from bot.db.repositories import StatsRepo
from sqlalchemy.ext.asyncio import AsyncSession as DbSession

logger = logging.getLogger(__name__)
router = Router(name="stats")

NOT_CONFIGURED = (
    "Статистика закрыта: не задан <code>ADMIN_IDS</code>.\n\n"
    "Добавь в переменные окружения на Render:\n"
    "<code>ADMIN_IDS={tg_id}</code>\n\n"
    "Это твой Telegram id — я его только что узнал из этого сообщения."
)


def _percent(part: int, whole: int) -> str:
    return f"{part / whole * 100:.0f}%" if whole else "—"


def _bar(value: int, peak: int, width: int = 10) -> str:
    """A chart that survives a phone, a monospace font and no image support."""
    if peak <= 0:
        return ""
    filled = max(1, round(value / peak * width)) if value else 0
    return "█" * filled + "·" * (width - filled)


@router.message(Command("stats"))
async def cmd_stats(message: Message, session: DbSession) -> None:
    tg_id = message.from_user.id if message.from_user else 0

    if not settings.admin_ids:
        # Told rather than refused: the person who owns the bot is the person
        # most likely to hit this, and they need the id to fix it.
        await message.answer(NOT_CONFIGURED.format(tg_id=tg_id))
        return

    if tg_id not in settings.admin_ids:
        # Silence, not a refusal. A refusal confirms the command exists.
        logger.info("stats refused for %s", tg_id)
        return

    repo = StatsRepo(session)
    data = await repo.overview()
    funnel = await repo.funnel()
    daily = await repo.daily()

    lines = [
        "📊 <b>SpeakOut — как идут дела</b>",
        "",
        "<b>Люди</b>",
        f"Всего открыли бота: <b>{data['total']}</b>",
        f"Новых за сутки: <b>{data['new_today']}</b> · за неделю: <b>{data['new_week']}</b>",
        f"Заходили за сутки: <b>{data['active_today']}</b> · "
        f"неделю: <b>{data['active_week']}</b> · месяц: <b>{data['active_month']}</b>",
    ]
    if data["blocked"]:
        lines.append(f"Заблокировали бота: <b>{data['blocked']}</b>")

    lines += [
        "",
        "<b>Два числа, которые важнее остальных</b>",
        f"Заговорили (сказали хоть что-то): <b>{data['spoke']}</b> "
        f"({_percent(data['spoke'], data['total'])} от всех)",
        f"Вернулись на второй день: <b>{data['returned']}</b> "
        f"({_percent(data['returned'], data['spoke'])} от заговоривших)",
        "",
        "<b>Где отваливаются</b>",
    ]

    peak = funnel[0][1] if funnel else 0
    for label, count in funnel:
        lines.append(f"<code>{_bar(count, peak)}</code> {count:>4}  {label}")

    lines += [
        "",
        "<b>Что происходит внутри</b>",
        f"Разговоров: <b>{data['conversations']}</b> "
        f"(с разбором до конца: {data['finished']})",
        f"Реплик: голосом <b>{data['voice']}</b> · "
        f"текстом <b>{data['text']}</b> · фото <b>{data['photos']}</b>",
        f"Наговорено: <b>{data['audio_minutes']:.0f} мин</b>",
        f"Открывали разбор по словам: <b>{data['reader_opens']}</b> · "
        f"повторение: <b>{data['review_opens']}</b>",
        f"Слов в изучении: <b>{data['cards']}</b> "
        f"(из них выбрано вручную: {data['tapped']})",
    ]

    if daily:
        busiest = max(count for _, _, count in daily)
        lines += ["", "<b>Последние две недели</b>"]
        for day, people, count in daily[-14:]:
            lines.append(
                f"<code>{day[5:]} {_bar(count, busiest, 8)}</code> "
                f"{count:>3} реплик · {people} чел."
            )

    lines += [
        "",
        f"<i>Токенов истрачено: {data['llm_in'] + data['llm_out']:,}</i>".replace(",", " "),
        "<i>Здесь только счётчики. Ничьих разговоров тут нет и не будет.</i>",
    ]

    await message.answer("\n".join(lines)[:4000])
