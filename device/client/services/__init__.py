"""App-level services that outlive any individual scene.

Currently just the bot service — the agent conversation persists
across scene navigation so the user can chat, launch an app, come
back, and still see the previous turns.
"""
from .bot import BotService

__all__ = ("BotService",)
