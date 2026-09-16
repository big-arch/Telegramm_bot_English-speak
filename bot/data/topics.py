"""Seed conversation topics.

Topics are not decoration either — a conversation with an explicit goal is the
difference between practice and small talk. "Conversations loop and stay
shallow" is the most common complaint about competing AI tutors, and the root
cause is that nothing in the session knows what it is trying to achieve.

`goal_prompt` is injected into the tutor's system prompt. Write it as a
direction for the tutor, not as a topic label.
"""

from __future__ import annotations

SEED_TOPICS: list[dict] = [
    {
        "slug": "free_talk",
        "title_en": "Free talk",
        "title_ru": "Свободный разговор",
        "emoji": "💬",
        "cefr_min": "A1",
        "cefr_max": "C2",
        "category": "general",
        "opening_line": "Hey! Good to see you. What's been going on with you lately?",
        "goal_prompt": (
            "No fixed agenda. Follow what they care about and dig one level deeper than "
            "they expect — ask why, ask for an example, ask what happened next. Your "
            "success condition is that they speak more than you do."
        ),
        "target_lexis": None,
    },
    {
        "slug": "about_you",
        "title_en": "Getting to know you",
        "title_ru": "Знакомство",
        "emoji": "👋",
        "cefr_min": "A1",
        "cefr_max": "A2",
        "category": "basics",
        "opening_line": "Hi! I'd love to know a bit about you. Where do you live?",
        "goal_prompt": (
            "Help them talk about themselves: where they live, what they do, who they "
            "live with, what a normal day looks like. Stay in present simple. Keep "
            "questions short and concrete."
        ),
        "target_lexis": "live, work, study, usually, every day, family",
    },
    {
        "slug": "coffee_order",
        "title_en": "Ordering coffee",
        "title_ru": "Заказ в кофейне",
        "emoji": "☕",
        "cefr_min": "A1",
        "cefr_max": "A2",
        "category": "travel",
        "opening_line": "Hi there, welcome in! What can I get for you today?",
        "goal_prompt": (
            "Play the barista. Take their order, ask a clarifying question (size, milk, "
            "for here or to go), handle a small complication like a card that doesn't "
            "work. Then step out of the role and let them try once more, faster."
        ),
        "target_lexis": "order, size, to go, change, receipt, refill",
    },
    {
        "slug": "airport",
        "title_en": "At the airport",
        "title_ru": "В аэропорту",
        "emoji": "✈️",
        "cefr_min": "A2",
        "cefr_max": "B1",
        "category": "travel",
        "opening_line": "Good morning! Can I see your passport and booking, please?",
        "goal_prompt": (
            "Play check-in, then security, then a gate change announcement they have to "
            "react to. Introduce one problem they must solve out loud — an overweight "
            "bag or a delayed connection."
        ),
        "target_lexis": "boarding pass, gate, delay, connection, aisle, overweight",
    },
    {
        "slug": "job_interview",
        "title_en": "Job interview",
        "title_ru": "Собеседование",
        "emoji": "💼",
        "cefr_min": "B1",
        "cefr_max": "C1",
        "category": "work",
        "opening_line": "Thanks for coming in. So — tell me about yourself.",
        "goal_prompt": (
            "Run a realistic interview: background, a strength, a real weakness, a "
            "difficult situation they handled, their questions for you. Push for "
            "specifics whenever they answer in generalities. Give one piece of honest "
            "feedback on structure at the end."
        ),
        "target_lexis": "responsible for, achieve, handle, background, strength, role",
    },
    {
        "slug": "small_talk_work",
        "title_en": "Small talk at work",
        "title_ru": "Small talk на работе",
        "emoji": "🏢",
        "cefr_min": "A2",
        "cefr_max": "B2",
        "category": "work",
        "opening_line": "Morning! Did you catch the end of that meeting yesterday?",
        "goal_prompt": (
            "Model the rhythm of workplace small talk: short exchanges, mirrored "
            "questions, easy exits. Teach them that ending a conversation politely is "
            "a skill too."
        ),
        "target_lexis": "catch up, by the way, anyway, I'd better, sounds good",
    },
    {
        "slug": "opinions",
        "title_en": "Sharing opinions",
        "title_ru": "Своё мнение",
        "emoji": "🗣️",
        "cefr_min": "B1",
        "cefr_max": "C1",
        "category": "general",
        "opening_line": "I've been thinking — do you reckon remote work actually makes people happier?",
        "goal_prompt": (
            "Ask for an opinion, then disagree gently and make them defend it. Push for "
            "reasons and examples. Teach hedging language — 'I'd say', 'it depends', "
            "'to be fair' — because directness translated from Russian often lands as "
            "blunt in English."
        ),
        "target_lexis": "I'd say, it depends, on the other hand, to be fair, actually",
    },
    {
        "slug": "storytelling",
        "title_en": "Telling a story",
        "title_ru": "Рассказать историю",
        "emoji": "📖",
        "cefr_min": "A2",
        "cefr_max": "B2",
        "category": "general",
        "opening_line": "Tell me about something that went wrong recently — I want the whole story.",
        "goal_prompt": (
            "Get them narrating in the past. Ask for the sequence: what happened first, "
            "then what, how it ended, how they felt. Past narrative is where Russian "
            "speakers' aspect habits show up most, so give them room to produce it."
        ),
        "target_lexis": "suddenly, in the end, it turned out, meanwhile, eventually",
    },
    {
        "slug": "doctor",
        "title_en": "At the doctor's",
        "title_ru": "У врача",
        "emoji": "🩺",
        "cefr_min": "A2",
        "cefr_max": "B1",
        "category": "life",
        "opening_line": "Come in, take a seat. So, what seems to be the problem?",
        "goal_prompt": (
            "Play the doctor. Get them describing symptoms, how long, how severe. Then "
            "give instructions they must confirm they understood."
        ),
        "target_lexis": "symptom, ache, sore, prescription, twice a day, get worse",
    },
    {
        "slug": "renting_flat",
        "title_en": "Renting a flat",
        "title_ru": "Аренда квартиры",
        "emoji": "🔑",
        "cefr_min": "B1",
        "cefr_max": "B2",
        "category": "life",
        "opening_line": "So this is the place. Any questions before I show you the kitchen?",
        "goal_prompt": (
            "Play the landlord. Make them ask questions rather than answer them — about "
            "the deposit, bills, the neighbours, what happens if something breaks. "
            "Asking good questions is a harder skill than answering."
        ),
        "target_lexis": "deposit, bills included, lease, landlord, notice, utilities",
    },
    {
        "slug": "movies_books",
        "title_en": "Films and books",
        "title_ru": "Фильмы и книги",
        "emoji": "🎬",
        "cefr_min": "A2",
        "cefr_max": "C1",
        "category": "general",
        "opening_line": "What's the last thing you watched that actually stayed with you?",
        "goal_prompt": (
            "Get them describing and evaluating, not just listing. Push past 'it was "
            "good' towards what specifically worked and who they'd recommend it to."
        ),
        "target_lexis": "plot, character, it's set in, I'd recommend, overrated",
    },
    {
        "slug": "future_plans",
        "title_en": "Plans and dreams",
        "title_ru": "Планы и мечты",
        "emoji": "🌅",
        "cefr_min": "A2",
        "cefr_max": "B2",
        "category": "general",
        "opening_line": "If nothing was in your way — what would you be doing a year from now?",
        "goal_prompt": (
            "Work the future forms: going to, will, might, hope to, planning on. Let "
            "them dream out loud, then make it concrete — what's the first step."
        ),
        "target_lexis": "going to, planning on, hope to, might, eventually, first step",
    },
    {
        "slug": "phone_call",
        "title_en": "A phone call",
        "title_ru": "Телефонный разговор",
        "emoji": "📞",
        "cefr_min": "B1",
        "cefr_max": "B2",
        "category": "work",
        "opening_line": "Hello, thanks for calling — how can I help?",
        "goal_prompt": (
            "Phone English without visual cues is genuinely harder. Play a support line. "
            "Make them explain a problem, spell something out, confirm details back, and "
            "ask you to repeat when they miss something."
        ),
        "target_lexis": "could you repeat, hold on, I'm calling about, spell that, get back to you",
    },
    {
        "slug": "disagreement",
        "title_en": "Polite disagreement",
        "title_ru": "Вежливое несогласие",
        "emoji": "⚖️",
        "cefr_min": "B2",
        "cefr_max": "C2",
        "category": "advanced",
        "opening_line": "I'll say something you probably disagree with: talent matters more than hard work. Go.",
        "goal_prompt": (
            "Argue with them. Make them push back, concede a point, and reframe. Focus "
            "on the softening language English needs and Russian doesn't — this is a "
            "register skill with social consequences, not a grammar point."
        ),
        "target_lexis": "I see your point, that said, I'd argue, not necessarily, fair enough",
    },
    {
        "slug": "explaining_work",
        "title_en": "Explaining what you do",
        "title_ru": "Рассказать о своей работе",
        "emoji": "🛠️",
        "cefr_min": "B1",
        "cefr_max": "C1",
        "category": "work",
        "opening_line": "I have no idea what your job actually involves. Explain it to me like I'm five.",
        "goal_prompt": (
            "Make them explain their work to a non-expert, then to a potential client, "
            "then in one sentence. Compression is the hard part and the useful one."
        ),
        "target_lexis": "basically, deal with, in charge of, so that, which means",
    },
    {
        "slug": "restaurant",
        "title_en": "At a restaurant",
        "title_ru": "В ресторане",
        "emoji": "🍽️",
        "cefr_min": "A1",
        "cefr_max": "B1",
        "category": "travel",
        "opening_line": "Good evening! Do you have a reservation?",
        "goal_prompt": (
            "Play the waiter. Seat them, take the order, recommend something, handle a "
            "problem with the dish, bring the bill. Include one thing they have to "
            "complain about politely."
        ),
        "target_lexis": "reservation, starter, medium rare, the bill, excuse me, I'd like",
    },
]
