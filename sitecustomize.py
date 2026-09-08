"""NakaFileBOT premium Telegram UI compatibility layer.

The main bot keeps Telegram MessageEntity data for configurable text/captions.
This module adds the one-shot button layout editor and maps Telegram custom
emoji entities to InlineKeyboardButton.icon_custom_emoji_id.
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


def _py_index_to_utf16(text, index):
    return len(text[:index].encode("utf-16-le")) // 2


def _entity_bounds(text, entity):
    start = _utf16_to_py_index(text, entity.offset)
    end = _utf16_to_py_index(text, entity.offset + entity.length)
    return start, end


def _style_and_label(raw):
    raw = raw.strip()
    style = None
    m = re.match(r"^#([grp])\s+", raw, re.IGNORECASE)
    if m:
        style = {"g": "success", "r": "danger", "p": "primary"}[m.group(1).lower()]
        raw = raw[m.end():].strip()
    return style, raw


def _parse_button_rows(text, entities):
    """Parse the full one-shot button layout.

    Newline = next row.
    && = same row.
    #G/#R/#P = green/red/primary button style.
    `label - URL` = URL button.
    `label - check` = access-check callback button.

    A leading Telegram custom emoji entity is stored as the button icon and
    removed from the visible label so Telegram does not show it twice.
    """
    if not text or "-" not in text:
        return []

    custom_entities = []
    for entity in entities or []:
        if getattr(entity, "type", None) != "custom_emoji":
            continue
        custom_id = getattr(entity, "custom_emoji_id", None)
        if not custom_id:
            continue
        start, end = _entity_bounds(text, entity)
        custom_entities.append((start, end, custom_id))

    rows = []
    absolute_row_start = 0
    for row_index, line in enumerate(text.splitlines()):
        line_start = absolute_row_start
        absolute_row_start += len(line) + 1
        if not line.strip():
            continue

        parsed_row = []
        # Keep exact Python offsets for each && segment.
        cursor = 0
        for raw_part in line.split("&&"):
            leading = len(raw_part) - len(raw_part.lstrip())
            part = raw_part.strip()
            if not part:
                cursor += len(raw_part) + 2
                continue

            part_start = line_start + cursor + leading
            cursor += len(raw_part) + 2

            match = re.match(
                r"^(.*?)\s+-\s+(https?://\S+|check(?::[^\s]+)?)\s*$",
                part,
                re.IGNORECASE,
            )
            if not match:
                return []

            raw_label = match.group(1).strip()
            destination = match.group(2).strip()
            style, label = _style_and_label(raw_label)

            # Calculate where the visible label starts inside the original
            # message, after optional #G/#R/#P and whitespace.
            style_match = re.match(r"^#([grp])\s+", raw_label, re.IGNORECASE)
            prefix_len = style_match.end() if style_match else 0
            raw_label_leading = len(match.group(1)) - len(match.group(1).lstrip())
            label_start = part_start + raw_label_leading + prefix_len

            icon_id = None
            remove_start = remove_end = None
            for ent_start, ent_end, custom_id in custom_entities:
                if ent_start == label_start:
                    icon_id = custom_id
                    remove_start, remove_end = ent_start, ent_end
                    break

            if remove_start is not None:
                # Remove the fallback emoji from the stored label. The actual
                # custom emoji will be rendered by icon_custom_emoji_id.
                local_start = remove_start - label_start
                local_end = remove_end - label_start
                label = label[:local_start] + label[local_end:]
                label = label.strip()

            kind = "check" if destination.lower().startswith("check") else "url"
            value = "" if kind == "check" else destination
            parsed_row.append([
                label,
                kind,
                value,
                style or "",
                icon_id or "",
                row_index,
            ])

        if parsed_row:
            rows.append(parsed_row)

    return rows


async def _capture_button_input(update, context):
    """Handle the whole button layout before the legacy button parser."""
    main = sys.modules.get("__main__")
    if main is None or not hasattr(main, "admin_sessions"):
        return

    msg = getattr(update, "message", None)
    user = getattr(update, "effective_user", None)
    if not msg or not user or not getattr(msg, "text", None):
        return
    if not getattr(main, "is_admin", lambda _uid: False)(user.id):
        return

    session = main.admin_sessions.get(user.id)
    if not session or session.get("action") not in {"add_button", "edit_button", "button_layout"}:
        return

    parsed_rows = _parse_button_rows(msg.text, getattr(msg, "entities", None))
    if not parsed_rows:
        return

    flat = [button for row in parsed_rows for button in row]
    cfg = session["draft"]

    # The new editor replaces the complete button layout in one operation.
    # This is intentionally different from the old one-button-at-a-time flow.
    cfg["buttons"] = flat
    session["action"] = "editor"

    # Keep a harmless local association as a diagnostic/fallback cache.
    for entity in getattr(msg, "entities", None) or []:
        if getattr(entity, "type", None) == "custom_emoji" and getattr(entity, "custom_emoji_id", None):
            _EMOJI_MAP[f"{user.id}|{msg.message_id}"] = entity.custom_emoji_id
    _save_map(_EMOJI_MAP)

    try:
        from telegram.ext import ApplicationHandlerStop
        await msg.reply_text(
            "🔘 Layout button masuk ke draft.\n\n"
            "🎨 #G = hijau • #R = merah • #P = biru\n"
            "↔️ && = satu baris • Enter = baris berikutnya\n"
            "💎 Custom Emoji Premium ikut disimpan.\n\n"
            "Belum tersimpan sampai tekan 💾 Simpan.",
            reply_markup=main.editor_menu(user.id, session["target"]),
        )
        raise ApplicationHandlerStop
    except ImportError:
        return


def _premium_build_keyboard(_original):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    def build_keyboard(buttons, code=None):
        rows = []
        explicit_rows = {}
        legacy_row = []

        for button in buttons or []:
            if len(button) < 2:
                continue

            label = button[0]
            kind = button[1]
            value = button[2] if len(button) > 2 else ""
            style = button[3] if len(button) > 3 and button[3] else None
            icon_id = button[4] if len(button) > 4 and button[4] else None
            row_id = button[5] if len(button) > 5 and button[5] != "" else None

            parsed_style, clean_label = _style_and_label(label)
            if parsed_style:
                style = style or parsed_style
                label = clean_label

            kwargs = {}
            if style in {"primary", "success", "danger"}:
                kwargs["style"] = style
            if icon_id:
                kwargs["icon_custom_emoji_id"] = str(icon_id)

            if kind == "check" and code:
                btn = InlineKeyboardButton(label, callback_data=f"check:{code}", **kwargs)
            elif kind == "url" and value:
                btn = InlineKeyboardButton(label, url=value, **kwargs)
            else:
                continue

            if row_id is not None:
                explicit_rows.setdefault(int(row_id), []).append(btn)
            else:
                # Backward compatibility for old three-item buttons.
                if len(legacy_row) >= 2:
                    rows.append(legacy_row)
                    legacy_row = []
                legacy_row.append(btn)

        if legacy_row:
            rows.append(legacy_row)
        for row_id in sorted(explicit_rows):
            rows.append(explicit_rows[row_id])

        return InlineKeyboardMarkup(rows) if rows else None

    return build_keyboard


try:
    from telegram.ext import Application, MessageHandler, filters

    _original_run_polling = Application.run_polling

    def _run_polling_with_naka_extensions(self, *args, **kwargs):
        main = sys.modules.get("__main__")
        if main is not None and hasattr(main, "build_keyboard"):
            main.build_keyboard = _premium_build_keyboard(main.build_keyboard)

        # Run before bot.py's normal text handler so the legacy parser cannot
        # overwrite the complete layout or discard MessageEntity data.
        self.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, _capture_button_input),
            group=-1,
        )
        return _original_run_polling(self, *args, **kwargs)

    Application.run_polling = _run_polling_with_naka_extensions
except Exception:
    # Optional compatibility layer must never prevent the bot from starting.
    pass
