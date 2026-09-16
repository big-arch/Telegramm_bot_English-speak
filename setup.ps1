# Установка SpeakOut одной командой. Windows.
#
#   powershell -ExecutionPolicy Bypass -File setup.ps1
#
# Скрипт можно запускать сколько угодно раз — он не сломает то, что уже настроено.

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Say  { param($m) Write-Host $m }
function OK   { param($m) Write-Host "OK  $m" -ForegroundColor Green }
function Warn { param($m) Write-Host "!   $m" -ForegroundColor Yellow }
function Die  { param($m) Write-Host "ОШИБКА: $m" -ForegroundColor Red; Read-Host "Нажми Enter"; exit 1 }

Say ""
Say "SpeakOut - установка"
Say "--------------------------------------"
Say ""

# --- 1. Python ---------------------------------------------------------
$PY = $null
foreach ($c in @("python", "python3", "py")) {
    if (Get-Command $c -ErrorAction SilentlyContinue) { $PY = $c; break }
}
if (-not $PY) {
    Die "Не найден Python. Установи с https://www.python.org/downloads/ и ОБЯЗАТЕЛЬНО поставь галочку 'Add Python to PATH' при установке."
}

$ver = & $PY -c "import sys; print('%d.%d' % sys.version_info[:2])"
$parts = $ver.Split(".")
if ([int]$parts[0] -lt 3 -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -lt 10)) {
    Die "Нужен Python 3.10 или новее, а установлен $ver. Обнови с https://www.python.org/downloads/"
}
OK "Python $ver"

# --- 2. ffmpeg — без него бот отвечает текстом, но не голосом ----------
# Без ffmpeg бот всё равно работает, просто отвечает текстом. Дать
# работающего текстового бота лучше, чем оставить человека ни с чем.
$NoVoice = $false
if (Get-Command ffmpeg -ErrorAction SilentlyContinue) {
    OK "ffmpeg на месте - голос будет работать"
} else {
    Warn "ffmpeg не установлен - попробую поставить."
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        try {
            winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
        } catch { }
        Say ""
        Warn "Если winget что-то установил - ЗАКРОЙ это окно, открой новое"
        Warn "и запусти скрипт снова, чтобы Windows увидел ffmpeg."
        Say ""
        $answer = Read-Host "Продолжить без голоса? (да / нет)"
        if ($answer -match '^(n|нет)') { exit 0 }
        $NoVoice = $true
    } else {
        $NoVoice = $true
    }
}

# --- 3. Зависимости ----------------------------------------------------
if (-not (Test-Path ".venv")) {
    Say ""
    Say "Создаю окружение и ставлю библиотеки. Это займёт пару минут..."
    & $PY -m venv .venv
}

& ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
& ".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt
if ($LASTEXITCODE -ne 0) { Die "Не удалось поставить библиотеки. Покажи мне текст ошибки выше." }
OK "Библиотеки установлены"

# --- 4. Ключи ----------------------------------------------------------
$hasEnv = (Test-Path ".env") -and (Select-String -Path ".env" -Pattern "^BOT_TOKEN=.+" -Quiet)
if ($hasEnv) {
    OK "Ключи уже настроены (файл .env). Чтобы изменить - открой .env в Блокноте."
} else {
    Say ""
    Say "Теперь три ключа. Все бесплатные, карта нигде не нужна."
    Say ""
    Say "  1. Токен бота  - @BotFather в Telegram -> /mybots -> твой бот -> API Token"
    Say "  2. Ключ Gemini - https://aistudio.google.com/apikey"
    Say "  3. Ключ Groq   - https://console.groq.com/keys"
    Say ""

    $BOT_TOKEN = Read-Host "1. Токен бота"
    if (-not $BOT_TOKEN) { Die "Токен пустой. Запусти скрипт снова." }

    $GEMINI = Read-Host "2. Ключ Gemini"
    if (-not $GEMINI) { Die "Ключ пустой. Запусти скрипт снова." }

    $GROQ = Read-Host "3. Ключ Groq"
    if (-not $GROQ) { Die "Ключ пустой. Запусти скрипт снова." }

    @"
BOT_TOKEN=$BOT_TOKEN
GEMINI_API_KEY=$GEMINI
GROQ_API_KEY=$GROQ

LLM_PROVIDER=gemini
STT_PROVIDER=groq
TTS_PROVIDER=edge
DB_DSN=sqlite+aiosqlite:///data/speakout.db

FREE_DAILY_TURNS=40
MAX_VOICE_SECONDS=120
LOG_LEVEL=INFO
"@ | Set-Content -Path ".env" -Encoding UTF8

    OK "Ключи сохранены в файл .env (он не попадёт в git)"
}

# --- 5. База и темы разговоров ----------------------------------------
Say ""
Say "Готовлю базу..."
& ".venv\Scripts\alembic.exe" upgrade head | Out-Null
if ($LASTEXITCODE -ne 0) { Die "Не удалось создать базу." }
& ".venv\Scripts\python.exe" -m scripts.seed | Out-Null
if ($LASTEXITCODE -ne 0) { Die "Не удалось загрузить темы разговоров." }
OK "База готова, темы загружены"

# --- 6. Запуск ---------------------------------------------------------
Say ""
Say "--------------------------------------"
Write-Host "Всё готово." -ForegroundColor Green
Say ""
if ($NoVoice) {
    Warn "ffmpeg не найден - бот будет отвечать ТЕКСТОМ, без голоса."
    Warn "Всё остальное работает. Голос включится сам, когда поставишь ffmpeg:"
    Warn "    winget install Gyan.FFmpeg"
    Say ""
}
Say "Запускаю бота. Открой его в Telegram и напиши /start"
Say ""
Say "Бот работает, пока открыто это окно."
Say "Остановить - Ctrl+C. Запустить снова - тот же скрипт."
Say "--------------------------------------"
Say ""

& ".venv\Scripts\python.exe" -m bot
