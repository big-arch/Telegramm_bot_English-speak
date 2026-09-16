"""Print the ElevenLabs voices available on your account.

The voice ids in bot/personas.py are ElevenLabs' long-standing defaults. Run
this to confirm they exist on your account — or to pick better ones — and paste
the ids back into the personas.

    python -m scripts.list_voices
"""

from __future__ import annotations

import asyncio

import httpx

from bot.config import settings


async def main() -> None:
    if settings.elevenlabs_api_key is None:
        print("ELEVENLABS_API_KEY is not set.")
        return

    async with httpx.AsyncClient(timeout=20.0) as http:
        response = await http.get(
            "https://api.elevenlabs.io/v1/voices",
            headers={"xi-api-key": settings.elevenlabs_api_key.get_secret_value()},
        )
        response.raise_for_status()
        voices = response.json().get("voices", [])

    if not voices:
        print("No voices returned.")
        return

    print(f"{'voice_id':<26} {'name':<18} labels")
    print("-" * 78)
    for voice in voices:
        labels = voice.get("labels") or {}
        summary = ", ".join(f"{k}={v}" for k, v in labels.items())
        print(f"{voice.get('voice_id', ''):<26} {voice.get('name', ''):<18} {summary}")


if __name__ == "__main__":
    asyncio.run(main())
