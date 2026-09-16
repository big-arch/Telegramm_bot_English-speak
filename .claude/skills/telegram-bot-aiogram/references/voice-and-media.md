# Voice, audio and files

## Telegram's file model

- `file_id` — how you re-send a file that Telegram already has. Free, instant, no upload. **Bot-specific**: a `file_id` from another bot will not work, and it can be invalidated.
- `file_unique_id` — stable identifier for the same physical file across bots. Use it as the deduplication key in your database; it cannot be used to download.
- `bot.get_file(file_id)` returns a `File` with `file_path`, valid for ~1 hour.

Hard limits on the public Bot API:

| Operation | Limit |
|---|---|
| Download (`getFile`) | 20 MB |
| Upload by the bot | 50 MB |
| Voice message duration | ~60 min, but 20 MB bites first |

A local Bot API server lifts these to 2 GB. Until then, reject long recordings politely up front (`message.voice.duration > 180` → ask for a shorter take) rather than failing after the download.

## Voice message types

`message.voice` is a recorded voice note (OGG/OPUS, always mono). `message.audio` is an uploaded music/audio file (any format, has a title). `message.video_note` is a round video. Handle them separately — `F.voice` will not match an uploaded mp3, which is a common "why doesn't it work when I send a file" report.

```python
@router.message(F.voice)
async def on_voice(message: Message, bot: Bot) -> None: ...

@router.message(F.audio | F.document)
async def on_uploaded_audio(message: Message) -> None:
    await message.answer("Please record a voice message rather than attaching a file 🎤")
```

## Download → transcribe → respond

The pattern that keeps the event loop free and the user informed:

```python
import asyncio
import tempfile
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.types import Message

router = Router(name="voice")

MAX_DURATION_SEC = 180


@router.message(F.voice)
async def handle_voice(message: Message, bot: Bot) -> None:
    voice = message.voice
    if voice.duration > MAX_DURATION_SEC:
        await message.answer("That's a long one — keep it under 3 minutes, please 🙂")
        return

    status = await message.answer("🎧 Listening…")

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"{voice.file_unique_id}.ogg"
        file = await bot.get_file(voice.file_id)
        await bot.download_file(file.file_path, destination=path)

        # Transcription is CPU/network bound and must not block the loop.
        transcript = await transcribe(path)

    feedback = await build_feedback(transcript)
    await status.edit_text(feedback)
```

`tempfile.TemporaryDirectory()` matters: a bot that writes to a fixed path races itself the moment two users speak at once, and a bot that never cleans up fills the disk in production. Name files by `file_unique_id` so collisions are impossible.

If transcription runs through a synchronous library, push it off the loop:

```python
async def transcribe(path: Path) -> str:
    return await asyncio.to_thread(_transcribe_sync, path)
```

For a remote API, use an async HTTP client (`httpx.AsyncClient`, `aiohttp`) with an explicit timeout. A hung request with no timeout holds a handler forever.

## Format conversion

Whisper-family models accept OGG/OPUS directly, so voice notes usually need no conversion. When something else is required (16 kHz mono WAV for a local ASR, or MP3 for a TTS round-trip), shell out to ffmpeg off-loop:

```python
async def to_wav16k(src: Path, dst: Path) -> None:
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-i", str(src),
        "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(dst),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {err.decode()[:500]}")
```

`asyncio.create_subprocess_exec` (not `subprocess.run`) keeps the loop responsive. Add ffmpeg to the Docker image explicitly — it is not in `python:slim`.

## Sending audio back

For generated speech (TTS feedback, model pronunciation), send as a voice note so it plays inline with a waveform:

```python
from aiogram.types import BufferedInputFile

await message.answer_voice(
    BufferedInputFile(ogg_bytes, filename="model.ogg"),
    caption="Here's how it sounds 👂",
)
```

Voice notes must be OGG/OPUS; sending an MP3 as `answer_voice` produces a file attachment instead of a playable bubble. `BufferedInputFile` sends from memory with no temp file; `FSInputFile` sends from disk.

**Cache aggressively.** The same prompt audio, the same model pronunciation of the same word, the same lesson intro — generate once, store the returned `file_id` in the database keyed by content hash, and re-send by `file_id` afterwards. This turns a TTS call plus an upload into a single API call, and for a vocabulary bot it is the difference between a trivial bill and a large one.

## Media groups

An album arrives as several separate updates sharing a `media_group_id`, with no "album complete" event. Buffer by `media_group_id` with a short debounce (~1 s) before processing, or you will handle a 5-photo album five times.

## Checklist for any media handler

- Duration/size guard before download, with a human-readable refusal.
- Temp directory per request, cleaned by context manager.
- Blocking work moved off the loop.
- Immediate acknowledgement message, edited with the result.
- `file_id` cached for anything you might send again.
- Explicit timeout on every external call.
