# Запуск без своего компьютера. Только браузер

Ничего скачивать и устанавливать не нужно. Терминал не нужен. Всё делается мышкой на трёх сайтах.

**Что где будет жить:**

| | Что это | Зачем |
|---|---|---|
| **GitHub** | код бота | уже есть, ничего делать не надо |
| **Supabase** | база данных | хранит прогресс, ошибки, слова |
| **Render** | компьютер в интернете | здесь программа работает круглосуточно |

Все три — бесплатно, карта не нужна.

---

# Часть 1. База данных (Supabase)

Нужно создать проект и взять из него одну строку.

1. Открой **https://supabase.com/dashboard**
2. **New project**. Имя любое, например `speakout`.
3. Придумай пароль базы и **сразу сохрани его в Блокнот** — его больше не покажут.
   > Возьми пароль **только из латинских букв и цифр**. Символы вроде `@ # / : ?` ломают строку подключения.
4. Регион выбери поближе — например Frankfurt.
5. **Create new project**, подожди пару минут.

**Теперь строка подключения:**

6. Слева внизу **Project Settings** (шестерёнка) → **Database**
7. Раздел **Connection string**, вкладка **URI**
8. Над строкой есть переключатель режима — выбери **Session pooler**

   > Самое важное место во всей инструкции. Вариантов три: Direct, Session, Transaction. Нужен **Session**. С Transaction бот будет падать через раз, и по логам это почти не диагностируется.

9. Скопируй строку. Выглядит так:

   ```
   postgresql://postgres.abcdefgh:[YOUR-PASSWORD]@aws-0-eu-central-1.pooler.supabase.com:5432/postgres
   ```

10. В Блокноте замени две вещи:
    - `[YOUR-PASSWORD]` → свой пароль из пункта 3 (вместе со скобками)
    - `postgresql://` в начале → `postgresql+asyncpg://`

    Должно получиться:

    ```
    postgresql+asyncpg://postgres.abcdefgh:ТвойПароль@aws-0-eu-central-1.pooler.supabase.com:5432/postgres
    ```

Отложи эту строку — понадобится в части 3.

---

# Часть 2. Ключи

| Что | Где взять | Как выглядит |
|---|---|---|
| Токен бота | Telegram → **@BotFather** → `/mybots` → SpeakOutEducation_bot → **API Token** | `1234567890:AAF-...` |
| Ключ Groq | **https://console.groq.com/keys** → Create API Key | `gsk_...` |
| Ключ Gemini *(необязательно)* | **https://aistudio.google.com/apikey** → Create API key | `AQ.Ab...` |

Ключ Groq обязателен — через него идёт распознавание речи. Он же может вести и сам разговор, так что минимум — два значения: токен и Groq.

Ключ Gemini делает диалог живее. Если он у тебя есть — подключим, если нет — бот работает и без него.

---

# Часть 3. Render — где всё будет работать

1. Открой **https://render.com** → **Get Started** → войди **через GitHub**.

2. В панели: **New +** → **Web Service**

3. **Connect a repository** → выбери **`Telegramm_bot_English-speak`**
   *(если репозитория нет в списке — нажми «Configure account» и дай Render доступ к нему)*

4. Заполни поля:

   | Поле | Значение |
   |---|---|
   | **Name** | `speakout` |
   | **Branch** | `claude/exciting-bohr-i24d3l` |
   | **Region** | Frankfurt |
   | **Language** / **Runtime** | **Docker** |
   | **Instance Type** | **Free** |

   > Runtime = **Docker**. Render сам найдёт `Dockerfile` в репозитории. Если выбрать Python, сборка пойдёт не так и не встанет ffmpeg — бот останется без голоса.

5. Пролистай до **Environment Variables**, добавь по одной кнопкой **Add Environment Variable**:

   | Key | Value |
   |---|---|
   | `BOT_TOKEN` | токен от BotFather |
   | `GROQ_API_KEY` | ключ Groq |
   | `DB_DSN` | строка из части 1 (та, что с `+asyncpg`) |
   | `LLM_PROVIDER` | `groq` |
   | `STT_PROVIDER` | `groq` |
   | `TTS_PROVIDER` | `edge` |

   Если есть ключ Gemini и хочешь диалог получше — добавь ещё две:

   | Key | Value |
   |---|---|
   | `GEMINI_API_KEY` | ключ Gemini |
   | `LLM_PROVIDER` | `gemini` *(вместо `groq`)* |

6. Нажми **Deploy Web Service**. Первая сборка идёт 5–10 минут.

---

# Часть 4. Включить вебхук

Бот запустился, но Telegram ещё не знает, куда слать сообщения.

1. Сверху страницы сервиса Render показывает адрес вида **`https://speakout-xxxx.onrender.com`**. Скопируй его целиком.

2. **Environment** слева → **Add Environment Variable**:

   | Key | Value |
   |---|---|
   | `WEBHOOK_BASE_URL` | твой адрес `.onrender.com` |

3. **Save, rebuild, and deploy**. Подожди минуту.

4. Открой вкладку **Logs**. Должно появиться:

   ```
   providers: llm=groq stt=groq tts=edge db=postgres mode=webhook
   billing: everything on free tiers — this run costs nothing
   webhook set to https://speakout-xxxx.onrender.com/tg/webhook
   listening on 0.0.0.0:10000
   ```

**Готово.** Открывай @SpeakOutEducation_bot и пиши `/start`. Компьютер можно выключать.

---

# Обязательный шаг: не дать боту заснуть

Render на бесплатном тарифе **выключает сервис после 15 минут без запросов**, а просыпается он около минуты. Без этого первое сообщение после паузы просто потеряется.

Лечится за две минуты, тоже бесплатно:

1. Открой **https://uptimerobot.com**, зарегистрируйся
2. **Add New Monitor**
3. **Monitor Type**: `HTTP(s)`
4. **Friendly Name**: `speakout`
5. **URL**: `https://твой-адрес.onrender.com/healthz`
6. **Monitoring Interval**: 5 минут
7. **Create Monitor**

Теперь кто-то стучится в бота каждые 5 минут, он не засыпает и отвечает сразу.

> Бесплатный тариф Render даёт 750 часов работы в месяц. Круглосуточно — это ~744 часа, то есть впритык помещается. Один сервис держать можно, два уже нет.

---

# Если что-то не так

| Что видишь | Что делать |
|---|---|
| Сборка идёт не по Dockerfile | В части 3 пункт 4 не выбран Runtime = **Docker**. Пересоздай сервис |
| В логах `Missing configuration` | Не добавлена переменная. В самом сообщении написано, какая |
| В логах `password authentication failed` | Неверный пароль в `DB_DSN` или в нём спецсимволы. Смени пароль базы в Supabase на буквы и цифры |
| В логах `prepared statement ... does not exist` | В Supabase взят **Transaction** pooler вместо **Session**. Часть 1, пункт 8 |
| Бот молчит, в логах `mode=polling` | Не задан `WEBHOOK_BASE_URL`. Часть 4 |
| Бот молчит, в логах всё зелёное | Не настроен UptimeRobot — сервис заснул. Секция выше |
| Отвечает текстом, но не голосом | В Docker-образе ffmpeg есть, такого быть не должно. Пришли логи |
| `rate limit` / `429` | Кончилась дневная квота Groq. Сбросится через сутки. Можно снизить: `GROQ_ASSESSOR_MODEL` = `llama-3.1-8b-instant` |

Застрял — **открой вкладку Logs, скопируй последние 20 строк и пришли мне**.

---

# Когда меняется код

Render сам пересобирает сервис при каждом пуше в ветку. Делать ничего не надо.
