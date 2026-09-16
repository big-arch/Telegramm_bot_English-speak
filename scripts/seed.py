"""Load conversation topics into the database.

Idempotent — safe to re-run after editing bot/data/topics.py, which is how you
update copy without a migration.

    python -m scripts.seed
"""

from __future__ import annotations

import asyncio

from bot.data.topics import SEED_TOPICS
from bot.db.base import engine, sessionmaker
from bot.db.models import Topic
from bot.db.upsert import insert


async def main() -> None:
    async with sessionmaker() as session:
        for row in SEED_TOPICS:
            stmt = (
                insert(Topic)
                .values(**row, is_active=True)
                .on_conflict_do_update(
                    index_elements=[Topic.slug],
                    set_={
                        "title_en": row["title_en"],
                        "title_ru": row["title_ru"],
                        "emoji": row["emoji"],
                        "cefr_min": row["cefr_min"],
                        "cefr_max": row["cefr_max"],
                        "category": row["category"],
                        "opening_line": row["opening_line"],
                        "goal_prompt": row["goal_prompt"],
                        "target_lexis": row["target_lexis"],
                        "is_active": True,
                    },
                )
            )
            await session.execute(stmt)
        await session.commit()

    print(f"Seeded {len(SEED_TOPICS)} topics.")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
