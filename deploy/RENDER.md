# Запуск. Только браузер, ~15 минут

Три сайта, всё мышкой. Ни терминала, ни карты.

---

## 1. База данных — Supabase

1. **https://supabase.com/dashboard** → **New project**
2. Имя `speakout`. Пароль — **только латиница и цифры** (`@ # / : ?` ломают строку). Сохрани его.
3. Регион — Frankfurt. **Create new project**, подожди ~2 минуты.
4. Шестерёнка **Project Settings** → **Database** → раздел **Connection string** → вкладка **URI**
5. Над строкой переключатель режима → выбери **Session pooler**

> ⚠️ Именно **Session**, не Transaction и не Direct. С Transaction бот падает через раз, и по логам это почти не находится. Это самое хрупкое место во всей инструкции.

6. Скопируй строку и в Блокноте замени в ней два куска:

| Было | Стало |
|---|---|
| `postgresql://` | `postgresql+asyncpg://` |
| `[YOUR-PASSWORD]` | твой пароль (скобки тоже убрать) |

Получится:
```
postgresql+asyncpg://postgres.abcdefgh:ТвойПароль@aws-0-eu-central-1.pooler.supabase.com:5432/postgres
```

---

## 2. Ключ Groq

**https://console.groq.com/keys** → Create API Key → скопируй (`gsk_...`). Показывают один раз.

Токен бота — у **@BotFather** → `/mybots` → SpeakOutEducation_bot → **API Token**.

---

## 3. Render

1. **https://render.com** → Get Started → войти **через GitHub**
2. **New +** → **Blueprint**
3. Выбери репозиторий **`Telegramm_bot_English-speak`**
4. **Branch** → `claude/exciting-bohr-i24d3l`
5. Render прочитает файл `render.yaml` из репозитория и всё настроит сам: Docker, бесплатный тариф, регион, health-check. Спросит только секреты:

| Поле | Что вставить |
|---|---|
| `BOT_TOKEN` | токен от BotFather |
| `GROQ_API_KEY` | `gsk_...` |
| `DB_DSN` | строка из шага 1 |
| `GEMINI_API_KEY` | оставь пустым |

6. **Apply**. Первая сборка 5–10 минут.

**Адрес вебхука подставлять не надо** — бот находит его сам.

---

## 4. Не дать боту заснуть — обязательно

Бесплатный Render выключает сервис после 15 минут тишины, а просыпается около минуты. Без этого шага первое сообщение после паузы теряется.

1. **https://uptimerobot.com** → зарегистрируйся
2. **Add New Monitor** → тип **HTTP(s)**
3. **URL**: `https://твой-адрес.onrender.com/healthz`
4. **Interval**: 5 минут → **Create**

---

## Готово

Открой **@SpeakOutEducation_bot** → `/start`. Компьютер можно выключать.

Во вкладке **Logs** в Render должно быть:

```
providers: llm=groq stt=groq tts=edge db=postgres mode=webhook
billing: everything on free tiers — this run costs nothing
webhook set to https://speakout-xxxx.onrender.com/tg/webhook
```

Главное — `mode=webhook` и `db=postgres`. Если там `mode=polling` или `db=sqlite`, что-то не доехало.

---

## Если не работает

| В логах | Причина |
|---|---|
| `Missing configuration` | Не заполнена переменная — в самом сообщении написано какая |
| `password authentication failed` | Пароль в `DB_DSN` неверный или со спецсимволами. Смени его в Supabase на буквы и цифры |
| `prepared statement ... does not exist` | Взят **Transaction** pooler вместо **Session**. Шаг 1, пункт 5 |
| `mode=polling` | Сервис создан не как Web Service. Пересоздай через **Blueprint** |
| `db=sqlite` | Не задан `DB_DSN` — прогресс будет стираться при каждом передеплое |
| `rate limit` / `429` | Кончилась дневная квота Groq. Сбросится через сутки |
| Всё зелёное, но бот молчит | Сервис заснул — не настроен UptimeRobot, шаг 4 |

Застрял — **скопируй последние 20 строк из вкладки Logs и пришли мне**.

---

## Потом

- Код обновится в ветке — Render пересоберёт сам, делать ничего не надо.
- Захочешь диалог поживее: заполни `GEMINI_API_KEY` и поменяй `LLM_PROVIDER` на `gemini` в **Environment**. Бесплатно.
