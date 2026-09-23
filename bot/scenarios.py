"""Role-play scenarios: a scene, a role for the partner, and something to get done.

Free conversation has one weakness every learner eventually feels: nothing is
at stake, so nothing is ever finished. A scenario fixes that with the oldest
device in language teaching — the task. You are not "talking about coffee",
you are getting a flat white with oat milk out of a barista who has questions.
The goals give each exchange a direction and a moment of done, which is the
feeling that makes someone open the app again tomorrow.

The goals are written to be checkable from what the learner actually says:
"order a drink and say what size" can be seen in a sentence, "communicate
confidently" cannot. A goal nobody can verify is a goal that is either never
marked or marked for free, and both teach the learner the checklist is
decoration.

Kept in code rather than in the database, like the personas: they are
content that changes with the product, reviewed in a diff, not data that
changes with use.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Goal:
    ru: str     # what the learner sees on the checklist
    check: str  # what the checker looks for, in English


@dataclass(frozen=True)
class Scenario:
    key: str
    emoji: str
    title_ru: str
    you_ru: str        # who the learner is in this scene
    role: str          # who the partner plays, in English, for the prompt
    setting: str       # the scene, in English
    opening: str       # the partner's first line
    goals: tuple[Goal, ...]
    levels: tuple[str, ...]


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        key="coffee",
        emoji="☕",
        title_ru="Кофейня",
        you_ru="Ты заходишь в кофейню в Лондоне перед работой.",
        role="a friendly but busy barista in a small London coffee shop",
        setting="Morning rush. There is a queue. The card machine is a bit slow today.",
        opening="Hi there! What can I get you this morning?",
        goals=(
            Goal("Заказать напиток и назвать размер",
                 "orders a specific drink AND states a size (small/medium/large, regular, etc.)"),
            Goal("Спросить что-то о меню или молоке",
                 "asks a question about the menu, milk options, a price, or an ingredient"),
            Goal("Расплатиться и вежливо попрощаться",
                 "says how they will pay (card/cash) or agrees to pay, AND thanks or says goodbye"),
        ),
        levels=("A1", "A2", "B1"),
    ),
    Scenario(
        key="smalltalk",
        emoji="🤝",
        title_ru="Small talk с коллегой",
        you_ru="Понедельник, ты встретил коллегу у кулера.",
        role="a chatty colleague from another team, met at the water cooler on a Monday",
        setting="Monday morning at the office kitchen. Neither of you is in a hurry yet.",
        opening="Morning! Good weekend?",
        goals=(
            Goal("Рассказать, как прошли выходные",
                 "describes something they did at the weekend, using a past-tense verb"),
            Goal("Спросить коллегу о чём-то в ответ",
                 "asks the colleague a question about their weekend, plans, or life"),
            Goal("Предложить пообедать вместе",
                 "suggests or invites the colleague to lunch, coffee, or meeting up later"),
        ),
        levels=("A2", "B1"),
    ),
    Scenario(
        key="passport",
        emoji="🛂",
        title_ru="Паспортный контроль",
        you_ru="Ты прилетел в Нью-Йорк, перед тобой офицер паспортного контроля.",
        role="a US border officer at JFK airport — polite, brief, and thorough",
        setting="Arrivals hall at JFK. A long flight behind you. The officer has your passport.",
        opening="Good afternoon. What's the purpose of your visit?",
        goals=(
            Goal("Объяснить цель поездки", "states the purpose of the visit (tourism, business, family, a conference, etc.)"),
            Goal("Сказать, на сколько приехал", "states how long they will stay"),
            Goal("Сказать, где будешь жить", "says where they will stay (a hotel name, a friend's place, an address)"),
        ),
        levels=("A2", "B1"),
    ),
    Scenario(
        key="hotel",
        emoji="🏨",
        title_ru="Заселение в отель",
        you_ru="Вечер, ты с чемоданом у стойки регистрации отеля.",
        role="a hotel receptionist at check-in, professional and warm",
        setting="Evening, a mid-range hotel in Edinburgh. Your room is booked, but not quite ready.",
        opening="Good evening, welcome! Do you have a reservation with us?",
        goals=(
            Goal("Назвать бронь и своё имя", "confirms they have a booking and gives their name"),
            Goal("Узнать про завтрак или Wi-Fi", "asks about breakfast times, Wi-Fi, or another hotel service"),
            Goal("Попросить что-то особенное", "makes a request: a quiet room, a late checkout, a different floor, extra pillows, etc."),
        ),
        levels=("A2", "B1", "B2"),
    ),
    Scenario(
        key="doctor",
        emoji="🩺",
        title_ru="У врача",
        you_ru="Ты заболел в поездке и пришёл к врачу.",
        role="a calm GP (family doctor) seeing a visitor from abroad",
        setting="A small clinic. You have had symptoms for a few days.",
        opening="Hello, come in, have a seat. So, what seems to be the problem?",
        goals=(
            Goal("Описать симптомы", "describes at least one symptom (pain, fever, cough, etc.)"),
            Goal("Сказать, как давно это началось", "says how long they have had the symptoms or when it started"),
            Goal("Спросить про лечение", "asks about medicine, treatment, what to do, or whether it is serious"),
        ),
        levels=("B1", "B2"),
    ),
    Scenario(
        key="refund",
        emoji="🛍",
        title_ru="Возврат товара",
        you_ru="Ты купил наушники, а они сломались через два дня.",
        role="a shop assistant in an electronics store — helpful, but bound by the returns policy",
        setting="An electronics shop. You have the headphones and the receipt.",
        opening="Hi, how can I help you today?",
        goals=(
            Goal("Объяснить, что не так", "explains what is wrong with the product"),
            Goal("Попросить вернуть деньги или заменить", "asks for a refund, a replacement, or an exchange"),
            Goal("Договориться о решении", "accepts, negotiates, or agrees on a concrete outcome"),
        ),
        levels=("B1", "B2"),
    ),
    Scenario(
        key="flat",
        emoji="🏠",
        title_ru="Аренда квартиры",
        you_ru="Ты звонишь по объявлению о сдаче квартиры.",
        role="a landlord answering a call about a one-bedroom flat for rent",
        setting="A phone call. The flat is in a good area, the price is a little high.",
        opening="Hello, this is Mark speaking. You're calling about the flat?",
        goals=(
            Goal("Узнать цену и что в неё входит", "asks about the rent and whether bills or utilities are included"),
            Goal("Договориться о просмотре", "arranges a viewing with a day or time"),
            Goal("Попробовать сторговаться", "tries to negotiate the price, deposit, or terms"),
        ),
        levels=("B1", "B2", "C1"),
    ),
    Scenario(
        key="interview",
        emoji="💼",
        title_ru="Собеседование",
        you_ru="Собеседование на работу в международной компании.",
        role="a hiring manager interviewing a candidate for a role in an international company",
        setting="A video interview. The manager is friendly but asks real follow-up questions.",
        opening="Thanks for joining us today. Could you start by telling me a bit about yourself?",
        goals=(
            Goal("Рассказать о себе и опыте", "describes their background or experience relevant to work"),
            Goal("Назвать сильную сторону с примером", "names a strength AND backs it with a concrete example"),
            Goal("Задать вопрос о работе", "asks the interviewer a question about the role, team, or company"),
        ),
        levels=("B1", "B2", "C1"),
    ),
    Scenario(
        key="pitch",
        emoji="📐",
        title_ru="Презентация проекта клиенту",
        you_ru="Ты архитектор и показываешь концепцию проекта клиенту.",
        role="a demanding client who commissioned a building design and has concerns about budget",
        setting="A meeting room. The concept drawings are on the table. The client likes it, but.",
        opening="Right, I've had a look at the concept. Talk me through it — what's the big idea?",
        goals=(
            Goal("Объяснить главную идею проекта", "explains the main idea or concept of the design"),
            Goal("Ответить на возражение", "responds to a concern about cost, time, or practicality with a reason or alternative"),
            Goal("Договориться о следующем шаге", "proposes or agrees on a next step: a revision, a meeting, a deadline"),
        ),
        levels=("B2", "C1"),
    ),
)

_BY_KEY = {s.key: s for s in SCENARIOS}


def get(key: str | None) -> Scenario | None:
    return _BY_KEY.get(key or "")


def for_level(level: str) -> list[Scenario]:
    """Every scenario, the ones pitched at this level first."""
    suited = [s for s in SCENARIOS if level in s.levels]
    rest = [s for s in SCENARIOS if level not in s.levels]
    return suited + rest


def parse_done(raw: str | None) -> set[int]:
    return {int(x) for x in (raw or "").split(",") if x.strip().isdigit()}


def format_done(done: set[int]) -> str:
    return ",".join(str(i) for i in sorted(done))


def card(scenario: Scenario, done: set[int], *, finished: bool = False) -> str:
    """The checklist message, edited in place as goals are met.

    Edited rather than re-sent: one card that fills in is a scoreboard, a new
    message per goal is noise the learner has to scroll past to keep talking.
    """
    lines = [
        f"{scenario.emoji} <b>{scenario.title_ru}</b>",
        f"<i>{scenario.you_ru}</i>",
        "",
        "<b>Твоя задача:</b>",
    ]
    for index, goal in enumerate(scenario.goals):
        mark = "✅" if index in done else "▫️"
        text = f"<s>{goal.ru}</s>" if index in done else goal.ru
        lines.append(f"{mark} {text}")

    total = len(scenario.goals)
    lines.append("")
    if finished:
        lines.append("🏆 <b>Сценарий пройден!</b>")
    else:
        filled = "●" * len(done) + "○" * (total - len(done))
        lines.append(f"<code>{filled}</code>  {len(done)} из {total} · говори голосом")
    return "\n".join(lines)
