# Установка SpeakOut одной командой. Windows.
#
#   powershell -ExecutionPolicy Bypass -File setup.ps1
#
# Скрипт можно запускать сколько угодно раз — он не сломает то, что уже настроено.
#
# Файл сохранён в UTF-8 С BOM намеренно: Windows PowerShell 5.1 без него
# читает кириллицу как мусор.

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
Set-Location $PSScriptRoot

function Say  { param($m) Write-Host $m }
function OK   { param($m) Write-Host "[OK] $m" -ForegroundColor Green }
function Warn { param($m) Write-Host "[!]  $m" -ForegroundColor Yellow }
function Die  {
    param($m)
    Write-Host ""
    Write-Host "ОШИБКА: $m" -ForegroundColor Red
    Write-Host ""
    Read-Host "Нажми Enter, чтобы закрыть"
    exit 1
}

Say ""
Say "SpeakOut - установка"
Say "--------------------------------------"
Say ""

# --- 1. Python ---------------------------------------------------------
# Осторожно: в Windows команда `python` может оказаться заглушкой Microsoft
# Store, которая просто открывает магазин и ничего не печатает. Поэтому
# кандидат считается годным только если он реально вернул номер версии.
$PY = $null
$PYVER = $null
foreach ($candidate in @("py", "python", "python3")) {
    if (-not (Get-Command $candidate -ErrorAction SilentlyContinue)) { continue }
    try {
        $out = & $candidate -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
    } catch { continue }
    if ($out -and $out -match '^\d+\.\d+$') { $PY = $candidate; $PYVER = $out.Trim(); break }
}

if (-not $PY) {
    Die @"
Не найден Python.

Скачай его здесь: https://www.python.org/downloads/
При установке ОБЯЗАТЕЛЬНО поставь галочку "Add python.exe to PATH"
(она внизу первого окна установщика).

Потом закрой это окно, открой новое и запусти скрипт снова.
"@
}

$parts = $PYVER.Split(".")
if ([int]$parts[0] -lt 3 -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -lt 10)) {
    Die "Нужен Python 3.10 или новее, а установлен $PYVER. Обнови с https://www.python.org/downloads/"
}
OK "Python $PYVER"

# --- 2. ffmpeg ---------------------------------------------------------
# Без него бот всё равно работает, просто отвечает текстом. Дать рабочего
# текстового бота лучше, чем оставить человека ни с чем.
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
        Warn "и запусти скрипт заново, иначе Windows не увидит ffmpeg."
        Say ""
        $answer = Read-Host "Продолжить прямо сейчас, но БЕЗ голоса? (да / нет)"
        if ($answer -notmatch '^(д|da|y)') { exit 0 }
        $NoVoice = $true
    } else {
        Warn "winget недоступен - продолжу без голоса."
        $NoVoice = $true
    }
}

# --- 3. Зависимости ----------------------------------------------------
$VPY = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $VPY)) {
    Say ""
    Say "Создаю окружение и ставлю библиотеки. Это займёт пару минут..."
    & $PY -m venv .venv
    if (-not (Test-Path $VPY)) { Die "Не удалось создать окружение .venv" }
}

& $VPY -m pip install --quiet --upgrade pip
& $VPY -m pip install --quiet -r requirements.txt
if ($LASTEXITCODE -ne 0) { Die "Не удалось поставить библиотеки. Покажи мне текст ошибки выше." }
OK "Библиотеки установлены"

# --- 4. Ключи ----------------------------------------------------------
$hasEnv = (Test-Path ".env") -and (Select-String -Path ".env" -Pattern "^BOT_TOKEN=.+" -Quiet)
if ($hasEnv) {
    OK "Ключи уже настроены (файл .env). Чтобы изменить - открой .env в Блокноте."
} else {
    Say ""
    Say "Нужно два значения. Оба бесплатные, карта нигде не нужна."
    Say ""
    Say "  1. Токен бота - @BotFather в Telegram -> /mybots -> твой бот -> API Token"
    Say "  2. Ключ Groq  - https://console.groq.com/keys"
    Say ""
    Say "Один ключ Groq закрывает и распознавание речи, и сам разговор."
    Say ""
    Say "Вставка в это окно: Ctrl+V или правая кнопка мыши. Потом Enter."
    Say ""

    $BOT_TOKEN = (Read-Host "1. Токен бота").Trim()
    if (-not $BOT_TOKEN) { Die "Токен пустой. Запусти скрипт снова." }

    $GROQ = (Read-Host "2. Ключ Groq").Trim()
    if (-not $GROQ) { Die "Ключ пустой. Запусти скрипт снова." }

    $envText = @"
BOT_TOKEN=$BOT_TOKEN
GROQ_API_KEY=$GROQ

LLM_PROVIDER=groq
STT_PROVIDER=groq
TTS_PROVIDER=edge
DB_DSN=sqlite+aiosqlite:///data/speakout.db

FREE_DAILY_TURNS=40
MAX_VOICE_SECONDS=120
LOG_LEVEL=INFO
"@

    # Пишем без BOM. Сам бот BOM переварит (python-dotenv его срезает), но
    # .env читают и другие инструменты — docker compose, скрипты, редакторы —
    # и вот они на BOM спотыкаются. Дешевле не создавать проблему вообще.
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText((Join-Path $PSScriptRoot ".env"), $envText, $utf8NoBom)

    OK "Ключи сохранены в файл .env (он не попадёт в git)"
}

# --- 5. База и темы разговоров ----------------------------------------
Say ""
Say "Готовлю базу..."
& $VPY -m alembic upgrade head 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Say ""
    & $VPY -m alembic upgrade head
    Die "Не удалось создать базу - текст ошибки выше."
}
& $VPY -m scripts.seed | Out-Null
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
Say "Запускаю бота. Открой @SpeakOutEducation_bot в Telegram и напиши /start"
Say ""
Say "Бот работает, пока открыто это окно."
Say "Остановить - Ctrl+C. Запустить снова - та же команда."
Say "--------------------------------------"
Say ""

& $VPY -m bot
