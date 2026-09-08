"""NakaFileBOT global content-protection policy.

Admins receive bot messages/media without Telegram content protection.
Ordinary users receive maximum Telegram Bot API content protection.
This is intentionally global so every current and future bot send path is covered.
"""

import os
import sqlite3


_ADMIN_IDS = {1137740036, 1779151962, 1943239073, 7186342193}
_OWNER_ID = 1137740036
_DB_NAME = "files.db"
_PATCHED = False


def _admin_ids():
    ids = set(_ADMIN_IDS)
    ids.add(_OWNER_ID)
    try:
        conn = sqlite3.connect(_DB_NAME, timeout=1)
        rows = conn.execute("SELECT user_id FROM admins").fetchall()
        conn.close()
        ids.update(int(row[0]) for row in rows)
    except Exception:
        pass
    return ids


def _chat_is_admin(chat_id):
    try:
        return int(chat_id) in _admin_ids()
    except Exception:
        return False


def _patch_class(cls):
    global _PATCHED
    for name in (
        "send_message",
        "send_photo",
        "send_video",
        "send_animation",
        "send_document",
        "send_audio",
        "send_voice",
        "send_video_note",
        "send_media_group",
        "copy_message",
        "forward_message",
        "forward_messages",
    ):
        original = getattr(cls, name, None)
        if original is None or getattr(original, "_naka_protection_patch", False):
            continue

        async def wrapped(self, *args, __original=original, **kwargs):
            chat_id = kwargs.get("chat_id")
            if chat_id is None and args:
                # PTB send methods normally receive chat_id as a keyword, but
                # keep positional compatibility where a caller supplies it.
                chat_id = args[0]
            kwargs["protect_content"] = not _chat_is_admin(chat_id)
            return await __original(self, *args, **kwargs)

        wrapped._naka_protection_patch = True
        setattr(cls, name, wrapped)
    _PATCHED = True


try:
    from telegram import Bot
    _patch_class(Bot)

    try:
        from telegram.ext import ExtBot
        _patch_class(ExtBot)
    except Exception:
        pass
except Exception:
    # If Telegram is unavailable during interpreter startup, bot.py will fail
    # normally and report the real dependency error.
    pass
