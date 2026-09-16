# Как запустить SpeakOut бесплатно

Бот — это программа, которая должна где-то работать. Пока она не запущена, @SpeakOutEducation_bot молчит.

> **Не хочешь возиться с терминалом и держать компьютер включённым?**
> → **[RENDER.md](RENDER.md)** — всё делается мышкой в браузере. Это рекомендуемый путь.

Ниже — варианты для тех, кому нужен терминал и полный контроль. Все бесплатны.

---

## Сначала: один ключ

| Ключ | Где взять | Бесплатный лимит |
|---|---|---|
| `GROQ_API_KEY` | [console.groq.com/keys](https://console.groq.com/keys) | ~8 часов аудио и тысячи запросов к модели в день |

Один ключ Groq закрывает и распознавание речи, и сам разговор. Выдаётся мгновенно, карта не нужна.

Голос (`edge-tts`) не требует ключа вообще. База — локальный файл SQLite.

Необязательно: ключ [Gemini](https://aistudio.google.com/apikey) делает диалог живее — добавь `GEMINI_API_KEY` и поставь `LLM_PROVIDER=gemini`.

Токен бота — у @BotFather → `/mybots` → SpeakOutEducation_bot → API Token.

---

## Вариант 1. На своём компьютере — 5 минут

Быстрее всего убедиться, что всё работает. Минус: бот жив, только пока включён компьютер.

```bash
git clone https://github.com/big-arch/Telegramm_bot_English-speak.git
cd Telegramm_bot_English-speak

# macOS:  brew install ffmpeg
# Ubuntu: sudo apt install ffmpeg
# Windows: winget install Gyan.FFmpeg

make install
cp .env.example .env    # вписать BOT_TOKEN и GROQ_API_KEY
make setup
make run
```

Открывай @SpeakOutEducation_bot и пиши `/start`.

---

## Вариант 2. Oracle Cloud — бесплатно и навсегда

Единственный облачный провайдер, который даёт постоянную виртуальную машину бесплатно без срока: 4 ARM-ядра и 24 ГБ памяти. Карту при регистрации спросят для верификации, но не списывают.

**1. Создать машину**

[cloud.oracle.com](https://cloud.oracle.com) → Compute → Instances → Create.
Образ **Ubuntu 24.04**, форма **VM.Standard.A1.Flex**, 1 OCPU и 6 ГБ достаточно с запасом. Сохрани SSH-ключ.

Если пишет «Out of capacity» — попробуй другую зону доступности или другой регион, это обычное дело для бесплатных ARM-машин.

**2. Поставить бота**

```bash
ssh ubuntu@<IP машины>

sudo apt update && sudo apt install -y python3-venv python3-pip ffmpeg git
git clone https://github.com/big-arch/Telegramm_bot_English-speak.git
cd Telegramm_bot_English-speak

make install
cp .env.example .env
nano .env          # вписать два значения, Ctrl+O, Enter, Ctrl+X
make setup
```

**3. Сделать так, чтобы работал всегда**

```bash
sudo cp deploy/speakout.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now speakout
```

Проверить:

```bash
systemctl status speakout
journalctl -u speakout -f       # живой лог
```

В логе при старте должно быть:

```
providers: llm=groq stt=groq tts=edge db=sqlite mode=polling
billing: everything on free tiers — this run costs nothing
```

**Обновить после изменений в коде:**

```bash
cd ~/Telegramm_bot_English-speak
git pull
.venv/bin/pip install -r requirements.txt
.venv/bin/alembic upgrade head
sudo systemctl restart speakout
```

> Oracle забирает машины, которые простаивают неделями. Работающий бот это предотвращает — он постоянно опрашивает Telegram.

---

## Вариант 3. Docker — где угодно

```bash
cp .env.example .env    # заполнить
docker compose up -d --build
docker compose logs -f
```

База лежит в `./data` и переживает пересборку образа. Подходит для любого хостинга с Docker: Render, своя VPS, Oracle Cloud.

---

## Что делать, если не работает

| Симптом | Причина |
|---|---|
| Бот не отвечает вообще | Неверный `BOT_TOKEN`, или процесс не запущен: `systemctl status speakout` |
| Отвечает текстом, но без голоса | Не установлен ffmpeg. Проверь: `ffmpeg -version` |
| «Не разобрал запись» на каждое голосовое | Кончился дневной лимит Groq или неверный `GROQ_API_KEY` |
| «Что-то сломалось на моей стороне» | Смотри `journalctl -u speakout -n 100` — там будет настоящая ошибка |
| Две реплики на одно сообщение | Запущено два процесса с одним токеном. Останови лишний |
| `rate limit` / `429` в логе | Кончилась дневная квота Groq. Сбросится через сутки. Снизить нагрузку: `GROQ_ASSESSOR_MODEL=llama-3.1-8b-instant` |

---

## Когда бесплатного перестанет хватать

Лимиты Groq считаются на аккаунт, а не на пользователя бота — комфортно до нескольких десятков активных людей.

Что делать дальше, по возрастанию цены:

1. `GROQ_ASSESSOR_MODEL=llama-3.1-8b-instant` — бесплатно, у младшей модели потолок заметно выше.
2. `FREE_DAILY_TURNS=20` — жёсткий потолок на человека, растягивает квоту.
3. `LLM_PROVIDER=gemini` — бесплатно и живее, но нужен второй ключ.
4. `TTS_PROVIDER=openai` — если голоса Edge перестанут устраивать, ~$15 за миллион знаков.
5. `LLM_PROVIDER=anthropic` — заметно лучше и разговор, и разбор ошибок. Платно.

Реальный расход по каждому пользователю пишется в таблицу `usage_days` с первого дня, так что момент «пора платить» ты увидишь по данным, а не по счёту.
