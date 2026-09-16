# Запуск без своего компьютера. Только браузер

Ничего скачивать и устанавливать не нужно. Терминал не нужен. Всё делается мышкой на трёх сайтах.

**Что где будет жить:**

| | Что это | Зачем |
|---|---|---|
| **GitHub** | код бота | уже есть, ничего делать не надо |
| **Supabase** | база данных | хранит прогресс, ошибки, слова |
| **Koyeb** | компьютер в интернете | здесь программа работает круглосуточно |

Все три — бесплатно.

---

# Часть 1. База данных (Supabase)

У тебя уже есть аккаунт. Нужно создать проект и взять из него одну строку.

1. Открой **https://supabase.com/dashboard**
2. **New project**. Имя любое, например `speakout`.
3. Придумай пароль базы и **сразу сохрани его в Блокнот** — его больше не покажут.
   > Возьми пароль **только из латинских букв и цифр**. Символы вроде `@ # / : ?` ломают строку подключения.
4. Регион выбери поближе к Европе — например Frankfurt.
5. Нажми **Create new project** и подожди пару минут, пока он поднимется.

**Теперь возьми строку подключения:**

6. Слева внизу **Project Settings** (шестерёнка) → **Database**
7. Найди раздел **Connection string**, вкладка **URI**
8. Выше есть переключатель режима — выбери **Session pooler**

   > Это важно. Там три варианта: Direct, Session, Transaction. Нужен именно **Session**. С Transaction бот будет случайным образом падать, и найти причину почти невозможно.

9. Скопируй строку. Она выглядит так:

   ```
   postgresql://postgres.abcdefgh:[YOUR-PASSWORD]@aws-0-eu-central-1.pooler.supabase.com:5432/postgres
   ```

10. В Блокноте **замени две вещи**:
    - `[YOUR-PASSWORD]` → на свой пароль из пункта 3 (вместе со скобками)
    - `postgresql://` в начале → на `postgresql+asyncpg://`

    Должно получиться:

    ```
    postgresql+asyncpg://postgres.abcdefgh:ТвойПароль@aws-0-eu-central-1.pooler.supabase.com:5432/postgres
    ```

Отложи эту строку — она понадобится в части 3.

---

# Часть 2. Ключи

Если ты их уже получал — пропусти.

| Ключ | Где | Как выглядит |
|---|---|---|
| Токен бота | Telegram → **@BotFather** → `/mybots` → SpeakOutEducation_bot → **API Token** | `1234567890:AAF-...` |
| Gemini | **https://aistudio.google.com/apikey** → Create API key | `AIza...` |
| Groq | **https://console.groq.com/keys** → Create API Key | `gsk_...` |

Оба ключа бесплатные, карта не нужна.

---

# Часть 3. Koyeb — где всё будет работать

1. Открой **https://www.koyeb.com** → **Sign up** → войди **через GitHub**. Так Koyeb сразу увидит твой репозиторий.

2. **Create Service** → **GitHub**

3. Выбери репозиторий **`Telegramm_bot_English-speak`**

4. **Branch** → выбери **`claude/exciting-bohr-i24d3l`**

5. **Builder** → выбери **Dockerfile**
   *(в репозитории он уже лежит, Koyeb найдёт его сам)*

6. **Instance** → выбери **Free**

7. **Service name** → впиши `speakout`
   Запомни адрес, который Koyeb покажет ниже — он будет вида
   `https://speakout-твоёимя.koyeb.app`

8. Найди раздел **Environment variables** и добавь их по одной кнопкой **Add variable**:

   | Имя | Значение |
   |---|---|
   | `BOT_TOKEN` | токен от BotFather |
   | `GEMINI_API_KEY` | ключ Gemini |
   | `GROQ_API_KEY` | ключ Groq |
   | `DB_DSN` | строка из части 1 (та, что с `+asyncpg`) |
   | `LLM_PROVIDER` | `gemini` |
   | `STT_PROVIDER` | `groq` |
   | `TTS_PROVIDER` | `edge` |

   Для `BOT_TOKEN`, `GEMINI_API_KEY`, `GROQ_API_KEY` и `DB_DSN` поставь тип **Secret**, если такой переключатель есть.

9. **Deploy**. Сборка займёт 3–5 минут. В логах увидишь строки вида `Successfully built`.

---

# Часть 4. Включить вебхук

Сейчас бот запустился, но Telegram ещё не знает, куда слать сообщения. Один последний шаг.

1. В Koyeb открой свой сервис. Сверху будет **Public URL** — скопируй его целиком, например `https://speakout-bigarch.koyeb.app`

2. **Settings** → **Environment variables** → **Add variable**:

   | Имя | Значение |
   |---|---|
   | `WEBHOOK_BASE_URL` | твой Public URL |

3. Нажми **Save** / **Redeploy** и подожди минуту.

4. В логах должно появиться:

   ```
   providers: llm=gemini stt=groq tts=edge db=postgres mode=webhook
   billing: everything on free tiers — this run costs nothing
   webhook set to https://speakout-....koyeb.app/tg/webhook
   listening on 0.0.0.0:8000
   ```

**Готово.** Открывай @SpeakOutEducation_bot и пиши `/start`. Компьютер можно выключать.

---

# Одна честная оговорка про бесплатный тариф

Koyeb на бесплатном плане **усыпляет сервис после часа без сообщений**. Первое сообщение после долгой паузы разбудит его, но ответ придёт секунд через 20, а иногда первое сообщение потеряется и его нужно отправить дважды.

Лечится за две минуты и тоже бесплатно:

1. Открой **https://uptimerobot.com**, зарегистрируйся
2. **Add New Monitor** → тип **HTTP(s)**
3. **URL**: `https://твой-адрес.koyeb.app/healthz`
4. **Monitoring Interval**: 5 минут
5. Сохрани

Теперь кто-то стучится в бота каждые 5 минут, он не засыпает и отвечает мгновенно.

---

# Если что-то не так

| Что видишь | Что делать |
|---|---|
| Сборка падает на `Dockerfile not found` | В пункте 5 не выбран Builder = Dockerfile |
| В логах `Missing configuration` | Не добавлена одна из переменных. В сообщении написано, какая именно |
| В логах `password authentication failed` | Неверный пароль в `DB_DSN`, или в пароле есть спецсимволы. Смени пароль базы в Supabase на буквы и цифры |
| В логах `prepared statement ... does not exist` | В Supabase скопирован **Transaction** pooler вместо **Session**. Вернись к части 1, пункт 8 |
| Бот молчит, в логах `mode=polling` | Не задан `WEBHOOK_BASE_URL`. Часть 4 |
| Бот отвечает текстом, но не голосом | Так не должно быть — в Docker-образе ffmpeg есть. Покажи мне логи |
| `resource exhausted` | Кончилась дневная бесплатная квота Gemini. Сбросится ночью |

Если застрял — **открой в Koyeb вкладку Logs, скопируй последние 20 строк и пришли мне**.

---

# Когда что-то меняется в коде

Koyeb сам пересобирает сервис при каждом пуше в ветку. Ничего делать не надо.
