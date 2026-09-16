#!/usr/bin/env bash
# Установка SpeakOut одной командой. macOS и Linux.
#
#   bash setup.sh
#
# Скрипт можно запускать сколько угодно раз — он не сломает то, что уже настроено.

set -uo pipefail

RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; BOLD=$'\033[1m'; OFF=$'\033[0m'

say()  { printf '%s\n' "$*"; }
ok()   { printf '%s✓%s %s\n' "$GREEN" "$OFF" "$*"; }
warn() { printf '%s!%s %s\n' "$YELLOW" "$OFF" "$*"; }
die()  { printf '%s✗ %s%s\n' "$RED" "$*" "$OFF" >&2; exit 1; }

cd "$(dirname "$0")"

say ""
say "${BOLD}SpeakOut — установка${OFF}"
say "──────────────────────────────────────────"
say ""

# ── 1. Python ─────────────────────────────────────────────────────────────
if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  die "Не найден Python. Установи его с https://www.python.org/downloads/ и запусти скрипт снова."
fi

PYV=$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])')
case "$PYV" in
  3.1[0-9]|3.[2-9][0-9]) ok "Python $PYV" ;;
  *) die "Нужен Python 3.10 или новее, а установлен $PYV. Обнови с https://www.python.org/downloads/" ;;
esac

# ── 2. ffmpeg — нужен для голоса, но без него бот всё равно работает ──────
# Не останавливаем установку, если не вышло: бот без ffmpeg отвечает текстом.
# Дать работающего текстового бота лучше, чем оставить человека ни с чем.
NO_VOICE=0
if command -v ffmpeg >/dev/null 2>&1; then
  ok "ffmpeg на месте — голос будет работать"
else
  warn "ffmpeg не установлен — попробую поставить."
  if command -v brew >/dev/null 2>&1; then
    brew install ffmpeg || NO_VOICE=1
  elif command -v apt-get >/dev/null 2>&1; then
    say "  Ставлю через apt (может спросить пароль)…"
    # `update` часто падает из-за посторонних репозиториев — это не повод
    # не пробовать саму установку.
    sudo apt-get update -qq >/dev/null 2>&1 || true
    sudo apt-get install -y ffmpeg || NO_VOICE=1
  else
    NO_VOICE=1
  fi

  if command -v ffmpeg >/dev/null 2>&1; then
    ok "ffmpeg установлен"
    NO_VOICE=0
  else
    NO_VOICE=1
  fi
fi

# ── 3. Зависимости ────────────────────────────────────────────────────────
if [ ! -d .venv ]; then
  say ""
  say "Создаю окружение и ставлю библиотеки. Это займёт пару минут…"
  "$PY" -m venv .venv || die "Не удалось создать окружение."
fi

.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt || die "Не удалось поставить библиотеки. Покажи мне текст ошибки выше."
ok "Библиотеки установлены"

# ── 4. Ключи ──────────────────────────────────────────────────────────────
if [ -f .env ] && grep -q '^BOT_TOKEN=.\+' .env 2>/dev/null; then
  ok "Ключи уже настроены (файл .env). Чтобы изменить — открой .env в редакторе."
else
  say ""
  say "${BOLD}Нужно два значения.${OFF} Оба бесплатные, карта нигде не нужна."
  say ""
  say "  1. Токен бота  — @BotFather в Telegram → /mybots → твой бот → API Token"
  say "  2. Ключ Groq   — https://console.groq.com/keys"
  say ""
  say "Один ключ Groq закрывает и распознавание речи, и сам разговор."
  say ""
  say "Вставка в терминале: Cmd+V (Mac) или Ctrl+Shift+V (Linux)."
  say "Текст при вставке может не отображаться — это нормально, просто нажми Enter."
  say ""

  read -r -p "1. Токен бота: " BOT_TOKEN
  [ -n "$BOT_TOKEN" ] || die "Токен пустой. Запусти скрипт снова."

  read -r -p "2. Ключ Groq: " GROQ_API_KEY
  [ -n "$GROQ_API_KEY" ] || die "Ключ пустой. Запусти скрипт снова."

  umask 077
  cat > .env <<ENV
BOT_TOKEN=$BOT_TOKEN
GROQ_API_KEY=$GROQ_API_KEY

LLM_PROVIDER=groq
STT_PROVIDER=groq
TTS_PROVIDER=edge
DB_DSN=sqlite+aiosqlite:///data/speakout.db

FREE_DAILY_TURNS=40
MAX_VOICE_SECONDS=120
LOG_LEVEL=INFO
ENV
  chmod 600 .env
  ok "Ключи сохранены в файл .env (он не попадёт в git)"
fi

# ── 5. База и темы разговоров ─────────────────────────────────────────────
say ""
say "Готовлю базу…"
.venv/bin/alembic upgrade head >/dev/null 2>&1 || die "Не удалось создать базу. Покажи мне вывод: .venv/bin/alembic upgrade head"
.venv/bin/python -m scripts.seed >/dev/null 2>&1 || die "Не удалось загрузить темы разговоров."
ok "База готова, темы загружены"

# ── 6. Запуск ─────────────────────────────────────────────────────────────
say ""
say "──────────────────────────────────────────"
say "${GREEN}${BOLD}Всё готово.${OFF}"
say ""
if [ "$NO_VOICE" = "1" ]; then
  warn "ffmpeg поставить не удалось — бот будет отвечать ТЕКСТОМ, без голоса."
  warn "Всё остальное работает. Голос включится сам, как только поставишь ffmpeg:"
  warn "    Mac:   brew install ffmpeg"
  warn "    Linux: sudo apt install ffmpeg"
  say ""
fi
say "Запускаю бота. Открой его в Telegram и напиши /start"
say ""
say "Бот работает, пока открыто это окно терминала."
say "Остановить — Ctrl+C. Запустить снова — bash setup.sh"
say "──────────────────────────────────────────"
say ""

exec .venv/bin/python -m bot
