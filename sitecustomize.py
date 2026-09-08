"""NakaFileBOT Telegram button extensions.

Loaded automatically by Python's site module before bot.py starts.
Adds Telegram's current inline-button styles and custom-emoji icons without
requiring secrets or a Premium account token in the bot.
"""
import json
import os
import re
import sys

_MAP_FILE = "button_emoji_map.json"


def _load_map():
    try:
        with open(_MAP_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_map(data):
    try:
        tmp = _MAP_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _MAP_FILE)
    except Exception:
        pass


_EMOJI_MAP = _load_map()


def _utf16_to_py_index(text, offset):
    units = 0
    for i, ch in enumerate(text):
        if units >= offset:
            return i
        units += len(ch.encode("utf-16-le")) // 2
    return len(text)


def _entity_text(text, entity):
    start = _utf16_to_py_index(text, entity.offset)
    end = _utf16_to_py_index(text, entity.offset + entity.length)
    return text[start:end]


def _style_and_label(raw):
    raw = raw.strip()
    style = None
    m = re.match(r"^#([grp])\s+", raw, re.IGNORECASE)
    if m:
        style = {"g": "success", "r": "danger", "p": "primary"}[m.group(1).lower()]
        raw = raw[m.end():].strip()
    return style, raw


def _parse_button_rows(text, entities):
    """Parse Group Help-style button syntax.

    Rows are separated by newlines, buttons in one row by &&.
    Each button is `[#g|#r|#p] label - URL` or `... - check`.
    A single custom emoji entity at the beginning of a button becomes
    Telegram's icon_custom_emoji_id.
    """
    if not text or " - " not in text:
        return []

    # Map each custom emoji to its button segment using UTF-16 offsets.
    emoji_segments = []
    for e in entities or []:
        if getattr(e, "type", None) == "custom_emoji" and getattr(e, "custom_emoji_id", None):
            emoji_segments.append((_entity_text(text, e), e.custom_emoji_id, e.offset, e.length))

    rows = []
    for row_index, line in enumerate(text.splitlines()):
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split("&&") if p.strip()]
        parsed_row = []
        for part in parts:
            m = re.match(r"^(.*?)\s+-\s+(https?://\S+|check(?::.*)?)\s*$", part, re.IGNORECASE)
            if not m:
                return []
            raw_label, destination = m.group(1).strip(), m.group(2).strip()
            style, label = _style_and_label(raw_label)
            kind = "check" if destination.lower().startswith("check") else "url"
            value = "" if kind == "check" else destination

            icon_id = None
            # Prefer a custom emoji whose entity text occurs in this button label.
            for emoji_text, custom_id, _off, _length in emoji_segments:
                if emoji_text and emoji_text in label:
                    icon_id = custom_id
                    # Only one custom emoji icon is supported per Telegram button.
                    break

            parsed_row.append([label, kind, value, style or "", icon_id or "", row_index])
        if parsed_row:
            rows.append(parsed_row)
    return rows


async def _capture_button_input(update, context):
    """Intercept button-editor messages before bot.py's old plain parser."""
    main = sys.modules.get("__main__")
    if main is None or not hasattr(main, "admin_sessions"):
        return
    msg = getattr(update, "message", None)
    user = getattr(update, "effective_user", None)
    if not msg or not user or not getattr(msg, "text", None):
        return
    if not getattr(main, "is_admin", lambda _uid: False)(user.id):
        return

    sessions = main.admin_sessions
    s = sessions.get(user.id)
    if not s or s.get("action") not in {"add_button", "edit_button"}:
        return

    parsed_rows = _parse_button_rows(msg.text, getattr(msg, "entities", None))
    if not parsed_rows:
        return

    # Persist the custom emoji association as a convenience for future edits.
    for row in getattr(msg, "entities", None) or []:
        if getattr(row, "type", None) == "custom_emoji" and getattr(row, "custom_emoji_id", None):
            key = f"{user.id}|{msg.text}"
            _EMOJI_MAP[key] = row.custom_emoji_id
    _save_map(_EMOJI_MAP)

    flat = [button for row in parsed_rows for button in row]
    cfg = s["draft"]
    if s.get("action") == "edit_button":
        idx = s.get("button_index")
        if idx is None or idx < 0 or idx >= len(cfg.get("buttons", [])):
            return
        cfg["buttons"][idx:idx + 1] = flat
    else:
        cfg.setdefault("buttons", []).extend(flat)

    s["action"] = "editor"
    try:
        from telegram.ext import ApplicationHandlerStop
        await msg.reply_text(
            "🔘 Button masuk draft.\n\n"
            "✅ Premium Emoji / warna / susunan baris ikut disimpan.\n"
            "Belum disimpan sampai tekan 💾 Simpan.",
            reply_markup=main.editor_menu(user.id, s["target"]),
        )
        raise ApplicationHandlerStop
    except ImportError:
        return


def _premium_build_keyboard(original):
    def build_keyboard(buttons, code=None):
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        rows = []
        current_legacy_row = []
        explicit_rows = {}

        for b in buttons or []:
            if len(b) < 2:
                continue
            label = b[0]
            kind = b[1]
            value = b[2] if len(b) > 2 else ""
            style = b[3] if len(b) > 3 and b[3] else None
            icon_id = b[4] if len(b) > 4 and b[4] else None
            row_id = b[5] if len(b) > 5 and b[5] != "" else None

            # Also understand inline style syntax in legacy button labels.
            parsed_style, clean_label = _style_and_label(label)
            if parsed_style:
                style = style or parsed_style
                label = clean_label

            kwargs = {"style": style} if style else {}
            if icon_id:
                kwargs["icon_custom_emoji_id"] = icon_id

            if kind == "check" and code:
                btn = InlineKeyboardButton(label, callback_data=f"check:{code}", **kwargs)
            elif kind == "url" and value:
                btn = InlineKeyboardButton(label, url=value, **kwargs)
            else:
                continue

            if row_id is not None:
                explicit_rows.setdefault(int(row_id), []).append(btn)
            else:
                if not current_legacy_row or len(current_legacy_row) >= 2:
                    current_legacy_row = []
                    rows.append(current_legacy_row)
                current_legacy_row.append(btn)

        if explicit_rows:
            # New syntax uses row IDs. Append those rows after legacy rows only
            # when the configuration mixes old and new buttons.
            for row_id in sorted(explicit_rows):
                rows.append(explicit_rows[row_id])

        return InlineKeyboardMarkup(rows) if rows else None

    return build_keyboard


try:
    # The Telegram package is installed by the time the app starts.
    from telegram.ext import Application, MessageHandler, filters

    _orig_run_polling = Application.run_polling

    def _run_polling_with_naka_extensions(self, *args, **kwargs):
        main = sys.modules.get("__main__")
        if main is not None and hasattr(main, "build_keyboard"):
            main.build_keyboard = _premium_build_keyboard(main.build_keyboard)

        # Group -1 runs before bot.py's normal group-0 text handler.
        self.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, _capture_button_input),
            group=-1,
        )
        return _orig_run_polling(self, *args, **kwargs)

    Application.run_polling = _run_polling_with_naka_extensions
except Exception:
    # Never prevent the bot from starting if this optional extension fails.
    pass
