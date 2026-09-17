"""The Mini App: a page inside Telegram where the tutor's words can be tapped.

Telegram gives a bot no way to know that a message's text was selected — text
selection belongs to the client's own UI, and no API reaches into it. So "tap a
word in the reply and see what it means" cannot be built in a chat message at
all. It can be built one layer up: a Mini App is a real web page, with real
text, where a tap is just a click.

The page is served by the same aiohttp application that already receives the
webhook, so this costs no extra host, no extra domain and no extra bill.
"""

from bot.webapp.routes import attach

__all__ = ["attach"]
