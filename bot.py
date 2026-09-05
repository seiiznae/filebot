import os
import sqlite3
import secrets
import threading
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, BotCommand
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("BOT_TOKEN belum diset di environment variable")

ADMIN_IDS = {1137740036, 1779151962, 1943239073, 7186342193}

CHANNEL_ID = -1001967813918
FREE_GROUP_ID = -1002228292417
MEMBERSHIP_GROUP_ID = -1002115664800

DEFAULT_CHANNEL_LINK = "https://t.me/Nakahoshi"
DEFAULT_FREE_GROUP_LINK = "https://t.me/+lYiuGXIVy1JkYWE9"
DEFAULT_PAYMENT_LINK = "https://t.me/nakanosqbot?start=NakaFileBOT"
DEFAULT_OWNER_LINK = "https://t.me/seiizn"

DB_NAME = "files.db"
db_lock = threading.Lock()
pending_batches = {}
admin_actions = {}

DEFAULT_START_TEXT = """╭━━━━━━━━━━━━━━━━━━━━╮
       ✦ NAKAHOSHI ✦
      FILE SHARE BOT
╰━━━━━━━━━━━━━━━━━━━━╯

🤖 BOT KHUSUS FILE SHARE
   NON-MEMBERSHIP USER

Jika Anda sudah bergabung ke Membership Nakahoshi, silakan langsung menikmati konten Membership.

🎬 @Nakahoshi

━━━━━━━━━━━━━━━━━━━━

Belum menjadi member?

⭐ Membership Nakahoshi
💰 Rp15.000 / 30 Hari

Dapatkan akses Membership dan nikmati konten lengkap.

👇 Pilih akses Anda:"""


def db():
    conn = sqlite3.connect(DB_NAME, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db_lock:
        conn = db()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS files (
                code TEXT PRIMARY KEY,
                file_id TEXT NOT NULL,
                file_type TEXT NOT NULL,
                caption TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS batches (
                code TEXT PRIMARY KEY,
                created_by INTEGER,
                created_at TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS batch_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_code TEXT NOT NULL,
                file_id TEXT NOT NULL,
                file_type TEXT NOT NULL,
                caption TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                first_seen TEXT,
                last_seen TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        defaults = {
            "start_text": DEFAULT_START_TEXT,
            "start_photo": "",
            "membership_price": "Rp15.000 / 30 Hari",
            "channel_link": DEFAULT_CHANNEL_LINK,
            "free_group_link": DEFAULT_FREE_GROUP_LINK,
            "payment_link": DEFAULT_PAYMENT_LINK,
            "owner_link": DEFAULT_OWNER_LINK,
        }
        for key, value in defaults.items():
            cur.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (key, value))
        conn.commit()
        conn.close()


def get_setting(key):
    with db_lock:
        conn = db()
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        conn.close()
    return row["value"] if row else ""


def set_setting(key, value):
    with db_lock:
        conn = db()
        conn.execute("INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)", (key, value))
        conn.commit()
        conn.close()


def save_user(user):
    if not user:
        return
    now = datetime.now().isoformat(timespec="seconds")
    with db_lock:
        conn = db()
        conn.execute("""
            INSERT INTO users(user_id, username, first_name, first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username,
                first_name=excluded.first_name,
                last_seen=excluded.last_seen
        """, (user.id, user.username or "", user.first_name or "", now, now))
        conn.commit()
        conn.close()


def is_admin(user_id):
    return user_id in ADMIN_IDS


async def member_is_inside(bot, chat_id, user_id):
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in {"member", "administrator", "creator", "restricted"}
    except Exception:
        return False


async def check_access(bot, user_id):
    if is_admin(user_id):
        return True

    # Membership Group is an alternative access route.
    if await member_is_inside(bot, MEMBERSHIP_GROUP_ID, user_id):
        return True

    channel_ok = await member_is_inside(bot, CHANNEL_ID, user_id)
    group_ok = await member_is_inside(bot, FREE_GROUP_ID, user_id)
    return channel_ok and group_ok


def access_keyboard(code):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⭐ JOIN MEMBERSHIP", url=get_setting("payment_link"))],
        [InlineKeyboardButton("📢 JOIN CHANNEL", url=get_setting("channel_link"))],
        [InlineKeyboardButton("👥 JOIN GROUP", url=get_setting("free_group_link"))],
        [InlineKeyboardButton("🔄 CEK AKSES", callback_data=f"check:{code}")],
    ])


def admin_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Statistik", callback_data="adm:stats"), InlineKeyboardButton("📦 Batch", callback_data="adm:batch")],
        [InlineKeyboardButton("🖼️ Start Image", callback_data="adm:image"), InlineKeyboardButton("✏️ Start Text", callback_data="adm:text")],
        [InlineKeyboardButton("🔘 Tombol & Link", callback_data="adm:links"), InlineKeyboardButton("💰 Harga", callback_data="adm:price")],
        [InlineKeyboardButton("📁 File", callback_data="adm:files"), InlineKeyboardButton("⚙️ Settings", callback_data="adm:settings")],
    ])


def cancel_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ BATAL", callback_data="adm:cancel")]])


def make_code(prefix="F"):
    return f"{prefix}_{secrets.token_urlsafe(10)}"


def get_file(code):
    with db_lock:
        conn = db()
        row = conn.execute("SELECT * FROM files WHERE code = ?", (code,)).fetchone()
        conn.close()
    return row


def get_batch(code):
    with db_lock:
        conn = db()
        rows = conn.execute("SELECT * FROM batch_items WHERE batch_code = ? ORDER BY id", (code,)).fetchall()
        conn.close()
    return rows


def create_file_record(file_id, file_type, caption):
    code = make_code("F")
    with db_lock:
        conn = db()
        conn.execute("INSERT INTO files(code, file_id, file_type, caption) VALUES (?, ?, ?, ?)",
                     (code, file_id, file_type, caption or ""))
        conn.commit()
        conn.close()
    return code


def create_batch(user_id, items):
    code = make_code("B")
    with db_lock:
        conn = db()
        conn.execute("INSERT INTO batches(code, created_by, created_at) VALUES (?, ?, ?)",
                     (code, user_id, datetime.now().isoformat(timespec="seconds")))
        conn.executemany(
            "INSERT INTO batch_items(batch_code, file_id, file_type, caption) VALUES (?, ?, ?, ?)",
            [(code, x[0], x[1], x[2] or "") for x in items]
        )
        conn.commit()
        conn.close()
    return code


def deep_link(context, code):
    username = context.bot.username
    return f"https://t.me/{username}?start={code}"


async def send_file(chat_id, item, bot):
    if item["file_type"] == "video":
        await bot.send_video(chat_id, item["file_id"], caption=item["caption"] or None, protect_content=True)
    elif item["file_type"] == "photo":
        await bot.send_photo(chat_id, item["file_id"], caption=item["caption"] or None, protect_content=True)


async def send_code(update, context, code):
    query = update.callback_query
    user_id = update.effective_user.id

    if not await check_access(context.bot, user_id):
        await query.answer("❌ Kamu belum memenuhi syarat akses.", show_alert=True)
        return

    await query.answer("Akses OK")
    await query.edit_message_text("✅ AKSES OK\n\n📤 File sedang dikirim...")

    if code.startswith("B_"):
        rows = get_batch(code)
        if not rows:
            await context.bot.send_message(update.effective_chat.id, "❌ Batch tidak ditemukan atau sudah dihapus.")
            return
        for row in rows:
            await send_file(update.effective_chat.id, row, context.bot)
    else:
        row = get_file(code)
        if not row:
            await context.bot.send_message(update.effective_chat.id, "❌ File tidak ditemukan atau sudah dihapus.")
            return
        await send_file(update.effective_chat.id, row, context.bot)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_user(update.effective_user)
    args = context.args

    if args:
        code = args[0]
        valid = code.startswith("F_") or code.startswith("B_")
        if not valid:
            await update.message.reply_text("❌ Link file tidak valid.")
            return

        if not await check_access(context.bot, update.effective_user.id):
            await update.message.reply_text(
                "🔒 AKSES BELUM TERSEDIA\n\nGabung Membership Nakahoshi, atau untuk akses gratis gabung Channel + Group terlebih dahulu.",
                reply_markup=access_keyboard(code),
            )
            return

        await update.message.reply_text("✅ AKSES OK\n\n📤 File sedang dikirim...")
        if code.startswith("B_"):
            rows = get_batch(code)
            if not rows:
                await update.message.reply_text("❌ Batch tidak ditemukan atau sudah dihapus.")
                return
            for row in rows:
                await send_file(update.effective_chat.id, row, context.bot)
        else:
            row = get_file(code)
            if not row:
                await update.message.reply_text("❌ File tidak ditemukan atau sudah dihapus.")
                return
            await send_file(update.effective_chat.id, row, context.bot)
        return

    text = get_setting("start_text")
    photo = get_setting("start_photo")
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⭐ JOIN MEMBERSHIP", url=get_setting("payment_link"))],
        [InlineKeyboardButton("📢 JOIN CHANNEL", url=get_setting("channel_link"))],
        [InlineKeyboardButton("👥 JOIN GROUP", url=get_setting("free_group_link"))],
        [InlineKeyboardButton("👤 OWNER BOT", url=get_setting("owner_link"))],
    ])

    if photo:
        await update.message.reply_photo(photo=photo, caption=text, reply_markup=keyboard)
    else:
        await update.message.reply_text(text, reply_markup=keyboard)


async def check_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    code = query.data.split(":", 1)[1]
    await send_code(update, context, code)


async def receive_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return
    save_user(user)

    file_id = None
    file_type = None
    caption = update.message.caption or ""

    if update.message.video:
        file_id = update.message.video.file_id
        file_type = "video"
    elif update.message.photo:
        file_id = update.message.photo[-1].file_id
        file_type = "photo"
    else:
        return

    pending = pending_batches.get(user.id)
    if pending is not None:
        pending.append((file_id, file_type, caption))
        await update.message.reply_text(f"✅ Ditambahkan ke batch. Total: {len(pending)} file.")
        return

    code = create_file_record(file_id, file_type, caption)
    await update.message.reply_text(
        f"✅ File tersimpan!\n\n🔗 Link:\n{deep_link(context, code)}\n\nCode: {code}"
    )


async def batch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    pending_batches[update.effective_user.id] = []
    await update.message.reply_text("📦 MODE BATCH AKTIF\n\nKirim semua video/foto yang ingin digabung.\nSetelah selesai ketik /done.\nUntuk membatalkan: /cancelbatch")


async def done_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return
    items = pending_batches.pop(user_id, None)
    if items is None:
        await update.message.reply_text("Tidak ada batch yang aktif.")
        return
    if not items:
        await update.message.reply_text("❌ Batch kosong.")
        return
    code = create_batch(user_id, items)
    await update.message.reply_text(
        f"✅ BATCH SELESAI\n\n📦 Total file: {len(items)}\n🔗 Link:\n{deep_link(context, code)}\n\nCode: {code}"
    )


async def cancel_batch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    pending_batches.pop(update.effective_user.id, None)
    await update.message.reply_text("❌ Batch dibatalkan.")


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text("👑 NAKAHOSHI ADMIN PANEL\n\nPilih menu:", reply_markup=admin_keyboard())


def stats_text():
    with db_lock:
        conn = db()
        files = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        batches = conn.execute("SELECT COUNT(*) FROM batches").fetchone()[0]
        batch_items = conn.execute("SELECT COUNT(*) FROM batch_items").fetchone()[0]
        users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        conn.close()
    return f"📊 STATISTIK\n\n📁 Single File: {files}\n📦 Batch: {batches}\n🗂️ File dalam Batch: {batch_items}\n👥 User pernah /start: {users}"


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("Tidak punya akses.", show_alert=True)
        return
    await query.answer()
    action = query.data.split(":", 1)[1]

    if action == "stats":
        await query.edit_message_text(stats_text(), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Kembali", callback_data="adm:home")]]))
    elif action == "batch":
        await query.edit_message_text("📦 BATCH\n\nKirim /batch untuk mulai batch.\nKirim file-file → /done untuk membuat link → /cancelbatch untuk batal.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Kembali", callback_data="adm:home")]]))
    elif action == "image":
        admin_actions[query.from_user.id] = "start_photo"
        await query.edit_message_text("🖼️ KIRIM FOTO\n\nKirim 1 foto sekarang. Foto itu akan menjadi gambar /start.", reply_markup=cancel_keyboard())
    elif action == "text":
        admin_actions[query.from_user.id] = "start_text"
        await query.edit_message_text("✏️ KIRIM TEXT BARU\n\nKirim teks yang ingin dipakai sebagai /start.", reply_markup=cancel_keyboard())
    elif action == "links":
        await query.edit_message_text(
            "🔘 LINK & TOMBOL\n\n"
            f"⭐ Membership: {get_setting('payment_link')}\n"
            f"📢 Channel: {get_setting('channel_link')}\n"
            f"👥 Group: {get_setting('free_group_link')}\n"
            f"👤 Owner: {get_setting('owner_link')}\n\n"
            "Untuk mengubah, gunakan command:\n"
            "/setpayment URL\n/setchannel URL\n/setgroup URL\n/setowner URL",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Kembali", callback_data="adm:home")]])
        )
    elif action == "price":
        admin_actions[query.from_user.id] = "price"
        await query.edit_message_text("💰 KIRIM HARGA BARU\n\nContoh: Rp15.000 / 30 Hari", reply_markup=cancel_keyboard())
    elif action == "files":
        with db_lock:
            conn = db()
            rows = conn.execute("SELECT code, file_type FROM files ORDER BY rowid DESC LIMIT 20").fetchall()
            conn.close()
        text = "📁 20 FILE TERBARU\n\n" + ("\n".join(f"{r['code']} — {r['file_type']}" for r in rows) if rows else "Belum ada file.")
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Kembali", callback_data="adm:home")]]))
    elif action == "settings":
        await query.edit_message_text("⚙️ SETTINGS\n\nKonfigurasi utama tersimpan di SQLite files.db.\nToken bot tidak disimpan di database/GitHub; token dibaca dari BOT_TOKEN.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Kembali", callback_data="adm:home")]]))
    elif action == "home":
        await query.edit_message_text("👑 NAKAHOSHI ADMIN PANEL\n\nPilih menu:", reply_markup=admin_keyboard())
    elif action == "cancel":
        admin_actions.pop(query.from_user.id, None)
        await query.edit_message_text("👑 NAKAHOSHI ADMIN PANEL\n\nPilih menu:", reply_markup=admin_keyboard())


async def set_link(update: Update, context: ContextTypes.DEFAULT_TYPE, key: str, label: str):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text(f"Gunakan: /{key.replace('_', '')} URL")
        return
    set_setting(key, " ".join(context.args).strip())
    await update.message.reply_text(f"✅ {label} berhasil diubah.")


async def setpayment(update, context):
    await set_link(update, context, "payment_link", "Payment link")

async def setchannel(update, context):
    await set_link(update, context, "channel_link", "Channel link")

async def setgroup(update, context):
    await set_link(update, context, "free_group_link", "Group link")

async def setowner(update, context):
    await set_link(update, context, "owner_link", "Owner link")


async def admin_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return
    action = admin_actions.get(user_id)
    if not action:
        return

    if action == "start_photo" and update.message.photo:
        set_setting("start_photo", update.message.photo[-1].file_id)
        admin_actions.pop(user_id, None)
        await update.message.reply_text("✅ Gambar /start berhasil diubah.")
    elif action == "start_text" and update.message.text:
        set_setting("start_text", update.message.text)
        admin_actions.pop(user_id, None)
        await update.message.reply_text("✅ Teks /start berhasil diubah.")
    elif action == "price" and update.message.text:
        set_setting("membership_price", update.message.text)
        admin_actions.pop(user_id, None)
        await update.message.reply_text("✅ Harga berhasil disimpan. Edit teks /start juga jika ingin menampilkan harga baru di sana.")


async def post_init(application: Application):
    await application.bot.set_my_commands([
        BotCommand("start", "Buka bot / akses file"),
        BotCommand("admin", "Admin panel"),
        BotCommand("batch", "Mulai batch file"),
        BotCommand("done", "Selesaikan batch"),
        BotCommand("cancelbatch", "Batalkan batch"),
    ])


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    print("ERROR:", context.error)


def main():
    init_db()
    app = Application.builder().token(TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("batch", batch_command))
    app.add_handler(CommandHandler("done", done_command))
    app.add_handler(CommandHandler("cancelbatch", cancel_batch))
    app.add_handler(CommandHandler("setpayment", setpayment))
    app.add_handler(CommandHandler("setchannel", setchannel))
    app.add_handler(CommandHandler("setgroup", setgroup))
    app.add_handler(CommandHandler("setowner", setowner))
    app.add_handler(CallbackQueryHandler(check_button, pattern=r"^check:"))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern=r"^adm:"))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO, receive_file), group=1)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, admin_text_input), group=2)
    app.add_error_handler(error_handler)

    print("Bot sedang berjalan...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
