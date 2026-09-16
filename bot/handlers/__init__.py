"""Router assembly.

Order is load-bearing: the first matching handler wins, and `conversation`
contains a catch-all for any non-command text. Registering it before the others
would silently swallow every other feature — the single most common cause of
"my handler never fires".
"""

from aiogram import Router

from bot.handlers import conversation, progress, review, settings, start

router = Router(name="root")

router.include_router(start.router)
router.include_router(settings.router)
router.include_router(review.router)
router.include_router(progress.router)
router.include_router(conversation.router)  # catch-all — must stay last

__all__ = ["router"]
